#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from click import option, group, argument, Path, File, confirm
from collections import namedtuple
from feedparser import parse
from ngram import NGram
from os import listdir, makedirs, chdir
from os.path import (join, isfile, isdir, getsize, dirname, basename, exists,
                     splitext)
from re import match, I
from glob import iglob, escape
from shutil import rmtree, move
from xmlrpc.client import ServerProxy
from pprint import pprint

import logging
log = logging.getLogger(__name__)

LOG_FORMAT = '[%(levelname)s] [%(relativeCreated)d] %(message)s'
EPISODES_REGEX = r'(.+)[\.  ][s|S]?([0-9]{1,2})[x|X|e|E]([0-9]{2}).*((1080p|2160p).*)'
MOVIES_REGEX = r'(?P<title>.+) \((?P<year>.+)\) \[1080p\]'
THRESHOLD = 0.6

# Found episodes for this run. Includes nzbs from nzbget and files on disk
found = []


@group()
@option('--log', type=File(mode='a'), help='Filename for log file')
@option('--debug', is_flag=True, default=False, help='Enable debug mode')
def main(log, debug):
    """ """
    # Setup logging
    if log:
        handler = logging.FileHandler(log.name)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    # Add handler to the root log
    logging.root.addHandler(handler)
    # Set log level
    level = logging.DEBUG if debug else logging.INFO
    logging.root.setLevel(level)


@main.command()
@argument('url')
@option('--library', type=Path(exists=True, dir_okay=True, resolve_path=True),
        help='Library containing TV Shows', multiple=True)
@option('--nzbget-url', default='http://apricot:6789/xmlrpc',
        help='Full URL to nzbget xmlrpc interface')
@option('--get-all', is_flag=True, default=False, help='Download all tv shows')
@option('--no-pilots', is_flag=True, default=False,
        help='Do not download the first episode of a season automatically')
@option('--no-upload', is_flag=True, default=False,
        help='Do not upload to Transmission')
def prequeue(url, library, nzbget_url, get_all, no_pilots,
             no_upload):
    """Parse an RSS feed for new nzbs.

    :url: URL to NZB RSS to load
    :library: Multiple paths to directories containing TV Shows
    :nzbget_url: URL to nzbget xmlrpc interface
    :get_all: Retrieve all episodes, even if they're not in TV Shows
    :no_pilots: Do not download the first episode of a season automatically

    """
    log.info('{s:-^80}'.format(s=' Start simpleget (prequeue)'))

    # NZBGet rpc-xml API
    nzbget = None if no_upload else ServerProxy(nzbget_url)

    # Retrieve the URL
    response = parse(url)
    if (response['bozo']):
        raise response['bozo_exception']
    log.info(f'Retrieved nzbs from "{url}"')

    # Match each item in the RSS feed to an episode regex
    for item in response['entries']:
        # Parse title (must be a valid episode name)
        try:
            title = item['title']
            log.debug(f'Processing "{title}"')
            # Process episode
            e = parse_episode(title)
            # Process file
            skip = True
            if exists_series(library, e.title):
                # Download if destination directory exists
                log.debug(f'Matched "{title}"')
                skip = False
            if not no_pilots and e.season == 1 and e.episode == 1:
                # Download the first episode of a new tv show
                skip = False
            if get_all:
                # Will invalidate any previous conditions
                skip = False
            if exists_episode(library, e, nzbget):
                log.info(f'"{title}" already exists, skipping')
                skip = True
            if skip:
                log.debug(f'Skipping "{title}"')
                continue
            log.info(f'Uploading "{title}" to nzbget')
            found.append(e)
            if nzbget:
                # Special stupidity: add .nzb to title, otherwise nzbget skips
                # the URL as "not being an NZB"
                title = title if title.endswith('.nzb') else title + '.nzb'
                # Upload to nzbget
                result = nzbget.append(title, item['link'], 'Series', 0, False,
                                       False, '', 0, 'SCORE',
                                       [('*unpack:', 'yes')])
                if result < 1:
                    raise ValueError(f'Could not upload nzb "{title}"')
        except ValueError:
            continue
    log.info('{s:-^80}'.format(s=' Finished simpleget (prequeue) '))


@main.command()
@option('--library', type=Path(exists=True, dir_okay=True, resolve_path=True),
        help='Library containing TV Shows', multiple=True)
@option('--filename', default='', help='File to process')
@option('--directory', type=Path(), default='',
        help='Directory containing file to process')
def postqueue(library, filename, directory):
    """Move files upon download by transmission.

    :library: Multiple paths to directories containing TV Shows
    :filename: Filename to process. Can be a relative path (use directory to
        complete path to file) or absolute
    :directory: Directory to process, or to find filename

    """
    log.info('{s:-^80}'.format(s=' Start simpleget (postqueue)'))

    # Source filename or directory
    path = source = join(directory, filename)
    if isdir(path):
        chdir(path)
        # Find the largest file in the source directory
        source = join(path,
                      sorted((getsize(s), s) for s in listdir(path))[-1][1])
    if not isfile(source):
        raise ValueError(f'Source "{source}" is not a file')

    # Try to find any part of the path to use as episode. Some downloads will
    # have a filename that is obfuscated, but the source directory is usable as
    # episode.
    e = False
    for p in reversed(source.split('/')):
        try:
            # Try to parse the path component
            e = parse_episode(p)
            break
        except ValueError:
            continue
    if not e:
        raise ValueError(f'Source "{source}" could not be parsed')

    log.debug(f'Processing file: "{source}" as "{e}"')

    # Get the extension for the filename (includes leading '.')
    _, ext = splitext(source)
    # Create an output filename
    destination = format_episode(library, e)
    if not destination.endswith(ext):
        destination += ext
    log.info(f'Writing "{source}" to "{destination}"')
    if exists(destination):
        raise ValueError(f'Destination "{destination}" already exists')

    # Create directory if it does not exist
    makedirs(dirname(destination), exist_ok=True)
    # Move file to new location
    move(source, destination)
    # Clean-up by removing the directory
    if isdir(path):
        log.info(f'Removing source directory {path}')
        rmtree(path)
    log.info('{s:-^80}'.format(s=' Finished simpleget (postqueue) '))


@main.command()
@argument('rename-dir', type=Path(exists=True, dir_okay=True,
          resolve_path=True), default='.')
def rename(rename_dir):
    """Rename all files in the target directory.

    :rename_dir: Directory to rename files in

    """
    # List all files in the directory
    for source in [d for d in listdir(rename_dir) if isfile(d)]:
        try:
            e = parse_episode(source)
            # Ask user to rename
            destination = basename(format_episode([rename_dir], e))
            if source == destination:
                continue
            if confirm(f'Rename "{source}" to "{destination}"?'):
                move(source, destination)
        except ValueError:
            continue


def exists_series(library, title):
    """Check if a series already exists. A series exists if a directory for the
    series is found in any of the library directories.

    :library: List of directories where the TV shows are found
    :title: Title of series to check
    :returns: Full path to series if series exists, None when not

    """
    for d in library:
        # Does this TV show already exist (fuzzy match)?
        G = NGram(listdir(d))
        found = G.find(title, THRESHOLD)
        if found is not None:
            return join(d, found)
    return None


def exists_episode(library, e, nzbget=None):
    """Check if an episode already exists. NZBGet queue/history is checked
    first to prevent spinning up the disk to check for file existence.

    Note that the interface for exists_episode() is not theV same as
    exists_series(), due to matching on Episode namedtuples. A path cannot be
    returned in that specific scenario.

    :library: List of directories where the TV shows are found
    :e: namedtuple as created by parse_episode()
    :nzbget: ServerProxy instance to nzbget API. Ignored when False
    :returns: True when episode exists, False when not

    """
    # Parsing is expensive with larger queues, only do this once
    if nzbget and len(found) == 0:
        # Get both download queue and history
        groups = nzbget.listgroups(0)
        groups += nzbget.history(False)

        # Include nzbs in groups to prevent re-uploading
        for nzb in groups:
            try:
                episode = parse_episode(nzb['NZBNicename'])
                if episode not in found:
                    found.append(episode)
            except ValueError:
                continue
    # Check if e is in found, to prevent going to disk
    if e in found:
        return True
    # Get the destination directory name for the tv show
    destination_dir = exists_series(library, e.title)
    if destination_dir is None:
        return False
    # Check if the episode is already available by episode number
    for f in iglob(escape(destination_dir) + '/**/*', recursive=True):
        try:
            episode = parse_episode(basename(f))
            if episode not in found:
                found.append(episode)
        except ValueError:
            continue
    # Final check if episode exists
    return e in found


def format_episode(library, e):
    """Format a file path based on the provided episode information.

    :library: List of directories where the TV shows are found
    :e: namedtuple as created by parse_episode()
    :returns: full path to destination file)
    """
    # Check if the series can be found in the library
    destination_dir = exists_series(library, e.title)
    if destination_dir is None:
        # Series not found, write to first (primary) directory in library
        destination_dir = join(library[0], e.title)
    # Format the title and trailer
    ti = e.title.lower().replace(' ', '.')
    tr = e.trailer.lower()
    # Create the full file path
    filename = f'{ti}.s{e.season:>02}e{e.episode:>02}.{tr}'
    return join(destination_dir, f'Season {e.season:>02}', filename)


def parse_episode(text):
    """Parse the filename of an episode for information such as title, season
    and episode.

    :text: Filename to parse
    :returns: nametuple('title', 'season', 'episode', 'trailer')

    """
    m = match(EPISODES_REGEX, text, I)
    if (m is None):
        raise ValueError(f'"{text}" is not a valid episode')
    # Store matched episode
    episode = namedtuple('episode', ['title', 'season', 'episode', 'trailer'])

    class Episode(episode):
        """ Helper class to match Episodes more broadly. """
        def __eq__(self, other):
            return (NGram.compare(self.title, other.title) > THRESHOLD and
                    self.season == other.season and
                    self.episode == other.episode)

    # Clean up title
    title = m.group(1).replace('_', ' ').replace('.', ' ').title()
    return Episode(title, int(m.group(2)), int(m.group(3)), m.group(4))

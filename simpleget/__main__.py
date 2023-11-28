#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .transmissionrpc import TransmissionRPC

from click import option, group, argument, Path, File, confirm
from collections import namedtuple
from feedparser import parse
from ngram import NGram
from os import listdir, makedirs, chdir
from os.path import join, isfile, isdir, getsize, dirname, basename, exists
from re import match, I
from shutil import rmtree, move
from xmlrpc.client import ServerProxy
from pprint import pprint

import logging
log = logging.getLogger(__name__)

LOG_FORMAT = '[%(levelname)s] [%(relativeCreated)d] %(message)s'
EPISODES_REGEX = r'(.+)[\. ][s|S]?([0-9]{1,2})[x|X|e|E]([0-9]{2}).*(1080p.*)'
MOVIES_REGEX = r'(?P<title>.+) \((?P<year>.+)\) \[1080p\]'
THRESHOLD = 0.6


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
@option('--tv-shows', type=Path(exists=True, dir_okay=True,
        resolve_path=True), help='Target directory containing the tv shows',
        default='.')
@option('--nzbget-url', default='http://apricot:6789/xmlrpc',
        help='Full URL to nzbget xmlrpc interface')
@option('--get-all', is_flag=True, default=False, help='Download all tv shows')
@option('--no-pilots', is_flag=True, default=False,
        help='Do not download the first episode of a season automatically')
@option('--no-upload', is_flag=True, default=False,
        help='Do not upload to Transmission')
def prequeue(url, tv_shows, nzbget_url, get_all, no_pilots, no_upload):
    """Parse an RSS feed for new nzbs.

    :url: URL to NZB RSS to load
    :tv_shows: Path to directory where the tv shows are stored
    :nzbget_url: URL to nzbget xmlrpc interface
    :get_all: Retrieve all episodes, even if they're not in TV Shows
    :no_pilots: Do not download the first episode of a season automatically

    """
    log.info('{s:-^80}'.format(s=' Start simpleget (prequeue)'))

    found = []
    if not no_upload:
        nzbget = ServerProxy(nzbget_url)
        # Include nzbs already being downloaded to prevent re-uploading
        for nzb in nzbget.listgroups(0):
            try:
                found.append(parse_episode(nzb['NZBNicename']))
            except ValueError:
                continue

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
            destination_dir = dirname(format_episode(tv_shows, e))
            # Process file
            skip = True
            if isdir(destination_dir):
                # Download if destination directory exists
                log.debug(f'Matched "{title}"')
                skip = False
            if not no_pilots and e.episode == 1:
                # Download the first episode of a season for all tv shows
                skip = False
            if get_all:
                # Will invalidate any previous conditions
                skip = False
            if e in found or exists_episode(tv_shows, e):
                log.info(f'"{title}" already exists, skipping')
                skip = True
            if skip:
                log.debug(f'Skipping "{title}"')
                continue
            log.info(f'Uploading "{title}" to nzbget')
            found.append(e)
            if not no_upload:
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
@option('--tv-shows', type=Path(exists=True, dir_okay=True,
        resolve_path=True), help='Target directory containing the tv shows',
        default='.')
@option('--filename', type=Path(),
        help='File to process')
@option('--directory', type=Path(), default='',
        help='Directory containing file to process')
def postqueue(tv_shows, filename, directory):
    """Move files upon download by transmission.

    :tv_shows: Path to directory where the tv shows are stored
    :filename: Filename to process. Can be a relative path (use directory to
        complete path to file) or absolute
    :directory: Directory to process, or to find filename

    """
    log.info('{s:-^80}'.format(s=' Start simpleget (postqueue)'))
    try:
        # Sanity check: can the provided filename be parsed by postqueue?
        parse_episode(filename)
    except ValueError:
        log.info(f'"{filename}" cannot be processed by simpleget')
        log.info('{s:-^80}'.format(s=' Finished simpleget (postqueue) '))
        return

    # Source filename or directory
    path = source = join(directory, filename)
    if isdir(path):
        chdir(path)
        # Find the largest file in the source directory
        source = join(path,
                      sorted((getsize(s), s) for s in listdir(path))[-1][1])
    if not isfile(source):
        raise ValueError(f'Source "{source}" is not a file')

    log.debug(f'Processing file: "{source}"')

    # Create an output filename
    destination = format_episode(tv_shows, parse_episode(basename(source)))
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
            destination = basename(format_episode(rename_dir, e))
            if source == destination:
                continue
            if confirm(f'Rename "{source}" to "{destination}"?'):
                move(source, destination)
        except ValueError:
            continue


def exists_episode(tv_shows, e):
    """Check if an episode already exists.

    :tv_shows: Directory where the TV shows are found
    :e: namedtuple as created by parse_episode()
    :returns: True if episode already exists, False when not

    TODO: cache the created Episodes

    """
    # Get the destination directory name
    destination_dir = dirname(format_episode(tv_shows, e))
    if not isdir(destination_dir):
        return False
    # Check if the episode is already available by episode number
    episodes = [parse_episode(f).episode for f in listdir(destination_dir)]
    return e.episode in episodes


def format_episode(tv_shows, e):
    """Format a file path based on the provided episode information.

    :tv_shows: Directory where the TV shows are found
    :e: namedtuple as created by parse_episode()
    :returns: Full path to destination file

    """
    # Does this TV show already exist (fuzzy match)?
    G = NGram([d for d in listdir(tv_shows)])
    found = G.find(e.title, THRESHOLD)
    title = found if found is not None else e.title
    # Format the title and trailer
    ti = title.lower().replace(' ', '.')
    tr = e.trailer.lower()
    # Create the full file path
    filename = f'{ti}.s{e.season:>02}e{e.episode:>02}.{tr}'
    return join(tv_shows, title, f'Season {e.season:>02}', filename)


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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from .transmissionrpc import TransmissionRPC

from click import option, group, argument, Path, File
from requests import get
from requests.exceptions import ConnectionError
from xml.etree import ElementTree
from re import match, I
from ngram import NGram
from collections import namedtuple
from os import listdir, environ, makedirs, chdir
from os.path import join, isfile, isdir, getsize, dirname, basename, exists
from shutil import rmtree, move
from pprint import pprint

import logging
log = logging.getLogger(__name__)

LOG_FORMAT = '[%(levelname)s] [%(relativeCreated)d] %(message)s'
EPISODES_REGEX = r'(.+)[\. ][s|S]?([0-9]{1,2})[x|X|e|E]([0-9]{2}).*(1080p.*)'
MOVIES_REGEX = r'(?P<title>.+) \((?P<year>.+)\) \[1080p\]'
THRESHOLD = 0.7


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
@argument('rss')
@option('--tv-shows', type=Path(exists=True, dir_okay=True,
        resolve_path=True), help='Target directory containing the tv shows',
        default='.')
@option('--get-all', is_flag=True, default=False, help='Download all tv shows')
@option('--no-pilots', is_flag=True, default=False,
        help='Do not download the first episode of a season automatically')
@option('--no-upload', is_flag=True, default=False,
        help='Do not upload to Transmission')
def prequeue(rss, tv_shows, get_all, no_pilots, no_upload):
    """Parse an RSS feed for new torrents.

    :rss: URL to RSS feed to load
    :tv_shows: Path to directory where the tv shows are stored
    :get_all: Retrieve all episodes, even if they're not in TV Shows
    :no_pilots: Do not download the first episode of a season automatically

    """
    log.info('{s:-^80}'.format(s=' Start simpleget '))
    # Retrieve the RSS feed
    response = get(rss)
    response.raise_for_status()
    # Load as XML
    rss = ElementTree.fromstring(response.content)

    # Match each item in the RSS feed to an episode regex
    G = NGram([d for d in listdir(tv_shows)])
    transmission_rpc = TransmissionRPC()
    for item in rss.iter('item'):
        # Parse title (must be a valid episode name)
        try:
            e = parse_episode(item.find('title').text)
            skip = True
            # Skip any episodes that do not meet the threshold
            found = G.find(e.title, THRESHOLD)
            if found is not None:
                log.info(f'TV show "{e.title}" matched against "{found}"')
                skip = False
            if not no_pilots and e.episode == 1:
                # Download the first episode of a season for all tv shows
                skip = False
            if get_all:
                # Will invalidate any previous conditions
                skip = False
            if (no_upload):
                # Mainly for testing & debugging
                skip = True
            if skip:
                log.debug(f'Skipping {e.title} {e.season}x{e.episode}')
                continue
            log.info(f'Uploading "{e.title} {e.season}x{e.episode}"')
            transmission_rpc.torrent_add(filename=item.find('link').text)
        except ValueError:
            continue
    log.info('{s:-^80}'.format(s=' Finished simpleget '))


@main.command()
@option('--tv-shows', type=Path(exists=True, dir_okay=True,
        resolve_path=True), help='Target directory containing the tv shows',
        default='.')
def postqueue(tv_shows):
    """Move files upon download by transmission.

    :tv_shows: Path to directory where the tv shows are stored

    """
    filename, directory = (environ['TR_TORRENT_NAME'],
                           environ['TR_TORRENT_DIR'])

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
    e = parse_episode(basename(source))

    # Does this TV show already exist (fuzzy match)?
    G = NGram([d for d in listdir(tv_shows)])
    found = G.find(e.title, THRESHOLD)
    title = found if found is not None else e.title

    # Create an output filename
    ti = title.lower().replace(' ', '.')
    tr = e.trailer.lower()
    output = f'{ti}.s{e.season:>02}e{e.episode:>02}.{tr}'
    destination = join(tv_shows, title, f'Season {e.season:>02}', output)
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
    episode = namedtuple('Episode', ['title', 'season', 'episode', 'trailer'])
    # Clean up title
    title = m.group(1).replace('_', ' ').replace('.', ' ').title()
    return episode(title, int(m.group(2)), int(m.group(3)), m.group(4))

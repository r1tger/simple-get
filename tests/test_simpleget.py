import pytest
from os import mkdir, environ, makedirs
from os.path import join, dirname, isfile, isdir
from click.testing import CliRunner
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import logging

from simpleget.__main__ import prequeue, postqueue


class RSSServer(BaseHTTPRequestHandler):
    def do_GET(self):
        """ """
        self.send_response(200)
        self.send_header('Content-type', 'text/xml')
        self.end_headers()
        with open('all.rss', 'rb') as f:
            self.wfile.write(f.read())


@pytest.fixture
def tv_shows(tmpdir, caplog):
    """ Set up simple-get environment """
    caplog.set_level(logging.DEBUG, logger='simpleget.__main__')
    test_dir = tmpdir.mkdir('simpleget')
    tv_shows = ['30 Coins/Season 02', 'Yellowjackets', 'The Walking Dead',
                'The Talking Dead']
    # Create directory of TV Shows
    for tv_show in tv_shows:
        makedirs(join(test_dir, tv_show))
    # Create a dummy file to test episode existence
    with open(join(test_dir, '30 Coins/Season 02',
                   '30.coins.s02e06.1080p.amzn.web-dl.ddp5.1.h.264-ntb.mkv'),
              'w'):
        pass
    # Make directory available to tests
    return test_dir


def test_prequeue(tv_shows, caplog):
    """ """
    # Create downloadable RSS file.
    server = HTTPServer(('localhost', 8080), RSSServer)
    server_thread = Thread(target=server.serve_forever)
    server_thread.start()
    # Test prequeue command
    runner = CliRunner()
    result = runner.invoke(prequeue,
                           ['--library', tv_shows, '--no-upload',
                            'http://localhost:8080/all.rss'])
    # Clean up
    server.shutdown()
    server_thread.join()
    # Asserts
    assert(result.exit_code == 0)


def test_postqueue_directory(tv_shows, caplog, tmpdir):
    """ """
    # Create torrent directory with video file
    torrent_name = 'Star.Trek.Picard.S03E09.1080p.WEB.H264-CAKES[rarbg]/'
    torrent_dir = tmpdir.mkdir('bt')
    source = join(torrent_dir, torrent_name,
                  'Star.Trek.Picard.S03E09.1080p.WEB.H264-CAKES.mkv')
    makedirs(dirname(source))
    with open(source, 'w'):
        pass
    # Test postqueue command
    runner = CliRunner()
    result = runner.invoke(postqueue, ['--library', tv_shows,
                                       '--directory', dirname(source)])
    print(caplog.text)
    # Asserts
    assert(result.exit_code == 0)
    destination = join(tv_shows, 'Star Trek Picard', 'Season 03',
                       'star.trek.picard.s03e09.1080p.web.h264-cakes.mkv')
    assert(isfile(destination))
    assert(not isdir(dirname(source)))


def test_postqueue_file(tv_shows, caplog, tmpdir):
    """ """
    # Create torrent directory with video file
    torrent_name = 'Star.Trek.Picard.S03E09.1080p.WEB.H264-CAKES.mkv'
    torrent_dir = tmpdir.mkdir('bt')
    source = join(torrent_dir, torrent_name)
    with open(source, 'w'):
        pass
    # Test postqueue command
    runner = CliRunner()
    result = runner.invoke(postqueue, ['--library', tv_shows,
                                       '--filename', torrent_name,
                                       '--directory', str(torrent_dir)])
    print(caplog.text)
    # Asserts
    assert(result.exit_code == 0)
    destination = join(tv_shows, 'Star Trek Picard', 'Season 03',
                       'star.trek.picard.s03e09.1080p.web.h264-cakes.mkv')
    assert(isfile(destination))
    assert(not isfile(source))
    assert(isdir(torrent_dir))


def test_postqueue_file_obfuscated(tv_shows, caplog, tmpdir):
    """ """
    # Create torrent directory with video file
    torrent_name = 'Star.Trek.Picard.S03E09.1080p.WEB.H264-CAKES[rarbg]/'
    torrent_dir = tmpdir.mkdir('bt')
    source = join(torrent_dir, torrent_name,
                  '0f9c374002dcc756021fa13b3824e8ce.mkv')
    makedirs(dirname(source))
    with open(source, 'w'):
        pass
    # Test postqueue command
    runner = CliRunner()
    result = runner.invoke(postqueue, ['--library', tv_shows,
                                       '--directory', dirname(source)])
    print(caplog.text)
    # Asserts
    assert(result.exit_code == 0)
    destination = join(tv_shows, 'Star Trek Picard', 'Season 03',
                       'star.trek.picard.s03e09.1080p.web.h264-cakes[rarbg].mkv')
    assert(isfile(destination))
    assert(not isdir(dirname(source)))

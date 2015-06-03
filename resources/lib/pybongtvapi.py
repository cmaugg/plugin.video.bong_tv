#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
The MIT License (MIT)

Copyright (c) 2015 Christian Maugg

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.



CHANGELOG
=========

0.2
===
* bugfix: Recording.is_scheduled() did'nt work

0.1
===
* first public release

"""

from contextlib import closing
from cStringIO import StringIO
import collections
import gzip
import htmlentitydefs
import httplib
import itertools
import json
import operator
import os
import re
import time
import urllib
import zlib

__author__ = 'Christian Maugg <software@christian.maugg.de>'
__version__ = version = '0.2'

USER_AGENT = 'pybongtvapi/' + version
HOST = 'bong.tv'
DEFAULT_COOKIE_DIR = os.path.join(os.path.expanduser('~'), '.pybongtvapi')
NAME2CODEPOINT_REGEX = re.compile('&(' + '|'.join(htmlentitydefs.name2codepoint) + ');')


class Error(Exception):
    pass


class RedirectError(Error):
    pass


class ClientError(Error):
    pass


class ServerError(Error):
    pass


class AuthorizationError(ClientError):
    pass


class NotFoundError(ClientError):
    pass


class UnprocessableEntityError(ClientError):
    pass


RecordingError = UnprocessableEntityError
UserCredentials = collections.namedtuple('UserCredentials', 'username password')
Actor = collections.namedtuple('Actor', 'name role')


def html_unescape(s):
    unescaped = ''
    if s:
        unescaped = re.sub(NAME2CODEPOINT_REGEX, lambda m: unichr(htmlentitydefs.name2codepoint[m.group(1)]), s)
    return unescaped.encode('utf-8') if type(unescaped) is unicode else unescaped


def http_request(method, url_path, cookie=None, params=None, headers=None, timeout=None):

    # normalize everything
    method = method.upper()
    headers = dict((k.lower(), v) for k, v in (headers or {}).items())
    body = ''

    headers['user-agent'] = USER_AGENT
    headers['accept'] = 'text/plain,application/json'
    headers['accept-encoding'] = 'gzip'
    if cookie is not None:
        headers['cookie'] = cookie

    if method == 'POST':
        body = urllib.urlencode(params or dict())
        headers['content-type'] = 'application/x-www-form-urlencoded'
    elif method == 'GET':
        if isinstance(params, dict):
            url_path += '?' + urllib.urlencode(params)
    elif method == 'DELETE':
        pass  # CHECK nothing to do here?
    else:
        raise ValueError('unsupported HTTP method: "{0}"'.format(method))

    with closing(httplib.HTTPConnection(HOST, timeout=timeout)) as connection:
        connection.request(method, url_path, body, headers)
        response = connection.getresponse()
        headers = dict((k.lower(), v) for k, v in response.getheaders())
        result = response.read() or ''
        if result[:2] == b'\037\213':  # probe for gzip header
            with closing(gzip.GzipFile(fileobj=StringIO(result))) as f:
                result = f.read()
        return response.status, result, headers


class API(object):

    def __init__(self, credentials=None, cookie=None):
        super(API, self).__init__()
        if isinstance(credentials, collections.Iterable):
            try:
                username, password = tuple(credentials)
            except Exception as error:
                raise Error('cannot parse user credentials: {0}'.format(error))
            else:
                self.username = str(username.encode('utf-8') if type(username) is unicode else username)
                self.password = str(password.encode('utf-8') if type(password) is unicode else password)
        elif cookie is not None:
            c = None
            if isinstance(cookie, basestring):
                if os.path.isfile(cookie):
                    c = open(cookie, mode='rt').read()
                else:
                    c = cookie
            elif hasattr(cookie, 'read') and callable(getattr(cookie, 'read')):
                c = cookie.read()
            if c is None:
                raise Error('cannot parse cookie')
            else:
                setattr(self, '___cookie', c)
        else:
            raise Error('no user credentials, no cookie .. what now?!?')

    def _check_http_status(self, status):
        if 100 <= status <= 299:  # 100er range --> informative, 200er range --> everything OK
            return True
        elif 300 <= status <= 399:
            raise RedirectError('HTTP redirect {0} not supported'.format(status))
        elif 400 <= status <= 499:
            if status == httplib.UNAUTHORIZED:
                raise AuthorizationError('user "{0}" not authorized (wrong password?)'.format(self.username))
            elif status == httplib.NOT_FOUND:
                raise NotFoundError()
            elif status == httplib.UNPROCESSABLE_ENTITY:
                raise RecordingError()
            else:
                raise ClientError('unexpected client HTTP error {0}'.format(status))
        elif 500 <= status <= 599:
            raise ServerError('unexpected server HTTP error {0}'.format(status))
        else:
            raise Error('unexpected HTTP error {0}'.format(status))

    @staticmethod
    def _write_cookie(cookie, cookie_filename):
        if not os.path.isdir(DEFAULT_COOKIE_DIR):
            os.makedirs(DEFAULT_COOKIE_DIR)
        cookie_path = os.path.join(DEFAULT_COOKIE_DIR, cookie_filename)
        with open(cookie_path, mode='wt') as cookie_file:
            cookie_file.write(cookie)

    @property
    def cookie(self):
        if not hasattr(self, '___cookie'):
            cookie = None
            cookie_filename = self.username + '-' + str(zlib.adler32(self.username + '|' + self.password)) + '.cookie'
            cookie_path = os.path.join(DEFAULT_COOKIE_DIR, cookie_filename)
            if os.path.isfile(cookie_path):
                cookie = open(cookie_path, mode='rt').read()
            else:
                params = dict(login=self.username, password=self.password)
                status, data, headers = http_request('POST', '/api/v1/user_sessions.json', params=params)
                if self._check_http_status(status):
                    cookie = headers['set-cookie']
                    self._write_cookie(cookie, cookie_path)
            if cookie is None:
                raise ValueError('no cookie')
            setattr(self, '___cookie', cookie)
        return getattr(self, '___cookie')

    def list_user_recordings(self, timeout=None):
        status, data, _ = http_request('GET', '/api/v1/recordings.json', self.cookie, timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('recordings') or dict()

    def create_recording(self, broadcast_id, timeout=None):
        params = dict(broadcast_id=int(broadcast_id))
        status, data, _ = http_request('POST', '/api/v1/recordings.json', self.cookie, params=params, timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('recording') or dict()

    def delete_recording(self, recording_id, timeout=None):
        status, _, _ = http_request('DELETE', '/api/v1/recordings/{0}.json'.format(int(recording_id)), self.cookie,
                               timeout=timeout)
        self._check_http_status(status)

    def list_channels(self, timeout=None):
        status, data, _ = http_request('GET', '/api/v1/channels.json', self.cookie, timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('channels') or dict()

    def get_broadcasts(self, channel_id, date, timeout=None):
        params = dict(channel_id=int(channel_id), date=date)
        status, data, _ = http_request('GET', '/api/v1/broadcasts.json', self.cookie, params=params, timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('broadcasts') or dict()

    def get_broadcast_details(self, broadcast_id, timeout=None):
        status, data, _ = http_request('GET', '/api/v1/broadcasts/{0}.json'.format(int(broadcast_id)), self.cookie,
                                  timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('broadcast') or dict()

    def search_broadcasts(self, search_pattern, timeout=None):
        params = dict(query=search_pattern)
        status, data, _ = http_request('GET', '/api/v1/broadcasts/search.json', self.cookie, params=params,
                                       timeout=timeout)
        if self._check_http_status(status):
            return json.loads(data).get('broadcasts') or dict()


class Broadcast(object):
    def __init__(self, data, api):
        super(Broadcast, self).__init__()
        if not type(api) is API:
            raise TypeError('expected type "{0}", got "{1}" instead'.format(API, type(api)))
        self._api = api
        self.broadcast_id = data['id']
        self.title = html_unescape(data['title'])
        self.subtitle = html_unescape(data['subtitle'])
        self.production_year = data['production_year']
        self.starts_at = time.localtime(data['starts_at_ms'])
        self.ends_at = time.localtime(data['ends_at_ms'])
        self.duration_in_secs = data['ends_at_ms'] - data['starts_at_ms']
        self.duration = int(self.duration_in_secs / 60.)
        self.country = html_unescape(data['country'])
        thumb_url_path = ((data.get('image') or dict()).get('href') or u'').encode('utf-8')
        self.thumb_url = ('http://' + HOST + thumb_url_path) if thumb_url_path else ''
        self.channel_id = data['channel_id']
        self.channel_logo_url = 'http://{host}/images/channel/b/{channel_id}.png'.format(host=HOST,
                                                                                         channel_id=self.channel_id)
        self.season = int((data.get('serie') or dict()).get('season') or 0)
        self.episode = int((data.get('serie') or dict()).get('episode') or 0)
        self.total_episodes = int((data.get('serie') or dict()).get('total_episodes') or 0)
        # FIXME categories is a tree-like structure
        self.categories = set(html_unescape(category['name']) for category in data['categories']
                              if category.get('name'))
        self.outline = html_unescape(data['short_text'])
        self.hd = True if data['hd'] else False
        self.channel_name = html_unescape(data['channel_name'])

    @property
    def _broadcast_details(self):
        if not hasattr(self, '___broadcast_details'):
            broadcast_details = self._api.get_broadcast_details(self.broadcast_id)
            setattr(self, '___broadcast_details', broadcast_details)
        return getattr(self, '___broadcast_details')

    @property
    def rating(self):
        return self._broadcast_details['rating']

    @property
    def votes(self):
        return self._broadcast_details['votes']

    @property
    def plot(self):
        return html_unescape(self._broadcast_details['long_text'])

    @property
    def hint(self):
        return html_unescape(self._broadcast_details['hint_text'])

    @property
    def directors(self):
        directors = [role['people'] for role in self._broadcast_details['roles'] if role['name'] == 'Regisseur']
        return sorted(set(html_unescape(director['name']) for director in itertools.chain(*directors)
                          if director.get('name')))

    @property
    def composers(self):
        composers = [role['people'] for role in self._broadcast_details['roles'] if role['name'] == 'Musik']
        return sorted(set(html_unescape(composer['name']) for composer in itertools.chain(*composers)
                          if composer.get('name')))

    @property
    def authors(self):
        authors = [role['people'] for role in self._broadcast_details['roles'] if role['name'] == 'Autor']
        return sorted(set(html_unescape(author['name']) for author in itertools.chain(*authors) if author.get('name')))

    @property
    def actors(self):
        actors = [role['people'] for role in self._broadcast_details['roles'] if role['name'] == 'Schauspieler']
        return sorted(set(Actor(html_unescape(actor['name']), html_unescape(actor['role'])) for actor in
                          itertools.chain(*actors) if actor.get('name')))

    def is_tvshow(self):
        return any([
            (self.season > 0) and (self.episode > 0),
        ])


class Recording(Broadcast):

    QUALITIES = QUALITY_HD, QUALITY_HQ, QUALITY_NQ = 'HD', 'HQ', 'NQ'

    def __init__(self, data, api):
        super(Recording, self).__init__(data['broadcast'], api)
        self.status = data['status']
        self.quality = data['quality']
        self.recording_id = data['id']
        self.urls = dict((file_data['quality'].upper(), file_data['href'].encode('utf-8'), ) for file_data in
                         data['files'])

    def is_recorded(self):
        return self.status.lower() == 'recorded'

    def is_scheduled(self):
        return self.status.lower() == 'scheduled'

    def get_url(self, recording_quality):
        if recording_quality not in Recording.QUALITIES:
            raise ValueError('expected one of "{0}", got "{1}" instead'.format(Recording.QUALITIES,
                                                                               recording_quality))
        return self.urls.get(recording_quality)

    @property
    def url(self):
        return self.get_url(Recording.QUALITY_HD) or self.get_url(Recording.QUALITY_HQ) or self.get_url(
            Recording.QUALITY_NQ)


class Channel(object):
    def __init__(self, data, api):
        super(Channel, self).__init__()
        if not type(api) is API:
            raise TypeError('expected type "{0}", got "{1}" instead'.format(API, type(api)))
        self._api = api
        self.channel_id = data['id']
        self.logo_url = 'http://{host}/images/channel/b/{channel_id}.png'.format(host=HOST, channel_id=self.channel_id)
        self.name = data['name']
        self.recordable = data['recordable']
        self.position = data['position']
        self.hd = data['hd']

    def is_hd(self):
        return True if self.hd else False

    def get_broadcasts_per_day(self, offset=0, timeout=None):
        date = time.strftime('%d-%m-%Y', time.localtime(time.time() + (int(offset) * 3600 * 24)))
        broadcasts = sorted([Broadcast(broadcast, self._api) for broadcast in self._api.get_broadcasts(
            self.channel_id, date=date, timeout=timeout)], key=operator.attrgetter('starts_at'))
        now = time.localtime()
        return tuple(broadcast for broadcast in broadcasts if broadcast.starts_at >= now)

    def get_broadcasts(self, offset=7, timeout=None):
        def producer():
            for i in range(offset):
                broadcasts = self.get_broadcasts_per_day(offset=i, timeout=timeout)
                if broadcasts:
                    yield broadcasts
                else:
                    break

        return tuple(itertools.chain(*tuple(producer())))

    broadcasts = property(fget=get_broadcasts)


class BongGuide(object):
    def __init__(self, api):
        super(BongGuide, self).__init__()
        if not type(api) is API:
            raise TypeError('expected type "{0}", got "{1}" instead'.format(API, type(api)))
        self._api = api

    def get_channels(self, timeout=None):
        return sorted([Channel(channel, self._api) for channel in self._api.list_channels(timeout=timeout)],
                      key=operator.attrgetter('position'))

    channels = property(fget=get_channels)

    def get_channel(self, channel_id, timeout=None):
        for channel in self.get_channels(timeout=timeout):
            if channel.channel_id == int(channel_id):
                return channel

    def search_broadcasts(self, search_pattern, timeout=None):
        return tuple(Broadcast(data, self._api) for data in self._api.search_broadcasts(search_pattern,
                                                                                        timeout=timeout))

    def search_broadcasts_per_channel(self, search_pattern, channel_id, timeout=None):
        return tuple(broadcast for broadcast in self.search_broadcasts(search_pattern, timeout=timeout) if
                     broadcast.channel_id == int(channel_id))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class BongSpace(object):
    def __init__(self, api):
        super(BongSpace, self).__init__()
        if not type(api) is API:
            raise TypeError('expected type "{0}", got "{1}" instead'.format(API, type(api)))
        self._api = api

    def get_recordings(self, timeout=None):
        return sorted([Recording(recording, self._api) for recording in self._api.list_user_recordings(
            timeout=timeout)], key=operator.attrgetter('starts_at'))

    recordings = property(fget=get_recordings)

    def create_recording(self, broadcast_id):
        return Recording(self._api.create_recording(int(broadcast_id)), self._api)

    def get_recording(self, recording_id, timeout=None):
        for recording in self.get_recordings(timeout=timeout):
            if recording.recording_id == int(recording_id):
                return recording

    def delete_recording(self, recording_id, timeout=None):
        try:
            self._api.delete_recording(int(recording_id), timeout=timeout)
        except NotFoundError:
            pass  # no such recording --> ignore

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

EPG = BongGuide
PVR = BongSpace

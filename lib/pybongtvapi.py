#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Copyright (c) 2013-2014, Christian Maugg
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Christian Maugg nor the names of
      its contributors may be used to endorse or promote products derived from
      this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

import ConfigParser
import collections
import functools
import httplib
import itertools
import json
import operator
import os
import re
import tempfile
import time
import urllib

from xml.sax import saxutils

__author__ = "Christian Maugg (pybongtvapi@christianmaugg.de)"
__version__ = "0.0.2"

_ENTITIES = dict([
    ("&auml;", "ä"),
    ("&ouml;", "ö"),
    ("&uuml;", "ü"),
    ("&Auml;", "Ä"),
    ("&Ouml;", "Ö"),
    ("&Uuml;", "Ü"),
    ("&szlig;", "ß"),
    ("&quot;", '"'),
    ("&#39;", "'"),
    ("&nbsp;", " "),
])


def _sanitize(value):
    if type(value) is unicode:
        value = value.encode("UTF-8")
    if type(value) is not str:
        raise TypeError()
    return saxutils.unescape(value, entities=_ENTITIES).strip().replace(chr(10), "").replace(r"\n", "")


# read config
_config_parser = ConfigParser.SafeConfigParser()
_COOKIE_PATH = os.path.join(tempfile.gettempdir(), ".pybongtvapi.session-cookie")

# the default configuration file (contains all properties)
DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "pybongtvapi.ini")

# the user's configuration file
USER_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".pybongtv", "pybongtvapi.ini")

# first, read the defaults. then, read the global configuration. then, read the user's configuration file
_config_parser.read([DEFAULT_CONFIG_FILE, USER_CONFIG_FILE])

BONGTVAPIv1_HOST = _config_parser.get("bongtvapi", "host")
BONGTVAPIv1_TIMEOUT = _config_parser.getfloat("bongtvapi", "timeout")
BONGTVAPIv1_LOGIN_URL = _config_parser.get("bongtvapi", "login_url")
BONGTVAPIv1_RECORDINGS_URL = _config_parser.get("bongtvapi", "recordings_url")
BONGTVAPIv1_RECORDING_URL_TEMPLATE = _config_parser.get("bongtvapi", "recording_url_template")
BONGTVAPIv1_CHANNELS_URL = _config_parser.get("bongtvapi", "channels_url")
BONGTVAPIv1_BROADCASTS_URL = _config_parser.get("bongtvapi", "broadcasts_url")
BONGTVAPIv1_BROADCAST_URL_TEMPLATE = _config_parser.get("bongtvapi", "broadcast_url_template")
BONGTVAPIv1_BROADCAST_SEARCH_URL = _config_parser.get("bongtvapi", "broadcast_search_url")
BONGTVAPIv1_APICALL_DELAY = _config_parser.getfloat("bongtvapi.compat", "apicall_delay")

WELL_KNOWN_TVSHOW_TITLES_REGEX = re.compile(_config_parser.get("user", "well_known_tvshow_titles_regex")) if _config_parser.get("user", "well_known_tvshow_titles_regex").strip() else None


# exceptions
class Error(Exception):
    pass


class AuthenticationError(Error):
    pass


class NoSuchItemError(Error):
    pass


class CannotCreateRecordingError(Error):
    pass


class ServerError(Error):
    pass


# helper classes and utilities
Actor = collections.namedtuple("Actor", "name role")


class delayed(object):
    """ decorator class, delays execution of a decorated function depending
    on the last invocation of some other decorated function """
    last_invocation_at = None

    def __init__(self, delay=BONGTVAPIv1_APICALL_DELAY):
        super(delayed, self).__init__()
        self.delay = delay

    def __call__(self, wrapped):
        def wrapper(*a, **kw):
            if type(delayed.last_invocation_at) is float:
                remaining = max(0, delayed.last_invocation_at - time.time() + self.delay)
                time.sleep(remaining)
            try:
                return wrapped(*a, **kw)
            finally:
                delayed.last_invocation_at = time.time()

        return functools.update_wrapper(wrapper, wrapped)


# module-private classes
class _Cookie(object):
    """ basic implementation of a Session Cookie """

    def __init__(self, cookie_string):
        super(_Cookie, self).__init__()
        if not isinstance(cookie_string, basestring):
            raise TypeError("Expected string, but got {0} instead!".format(type(cookie_string)))
        if len(cookie_string) < 1:
            raise ValueError("Cookie string is empty!")
        self._cookie_string = cookie_string

    def is_expired(self):
        # FIXME not implemented
        return False

    def __str__(self):
        return self._cookie_string


def _make_exception_from_http_status_code(status_code, message=None):
    message = message or "HTTP status code {0}: {1}".format(int(status_code), httplib.responses.get(int(status_code)))
    exception = {
        401: AuthenticationError,
        404: NoSuchItemError,
        422: CannotCreateRecordingError,
        502: ServerError,
    }.get(int(status_code), Error)
    return exception(message)


# public classes
class API(object):
    """ Provides access to the bong.tv-server, implements the bong.tv-API """

    def __init__(self, username, password):
        """  initializes this bong.tv-API object. sets username and password, and
        loads an eventually existing HTTP session cookie (used for authentication) """
        super(API, self).__init__()
        self.username = username
        self.password = password
        
        if os.path.isfile(_COOKIE_PATH):
            # yes, that's correct: the setter loads the cookie from cookie_path!
            self._set_cookie(_COOKIE_PATH)

    def _set_username(self, value):
        """ 
        sets the bong-tv-API username. Expects a string of more than zero 
        characters length
        @raise ValueError: raised when the username is too short
        @raise TypeError: raised when the value's type is no instance of basestring   
        """
        if isinstance(value, basestring):
            if len(value) > 0:
                setattr(self, "__username__", value)
            else:
                raise ValueError("Invalid username length")
        else:
            raise TypeError("Expected some string as username, but got {0} instead".format(type(value)))

    def _get_username(self):
        """ 
        @return: the username used when authenticating with the bong.tv-API 
        @raise AttributeError: raised when the username is not set 
        """
        return getattr(self, "__username__")

    def _set_password(self, value):
        """ 
        sets the bong-tv-API password. Expects a string of more than zero 
        characters length
        @raise ValueError: raised when the password is too short
        @raise TypeError: raised when the value's type is no instance of basestring  
        """
        if isinstance(value, basestring):
            if len(value) > 0:
                setattr(self, "__password__", value)
            else:
                raise ValueError("Invalid password length")
        else:
            raise TypeError("Expected some string as password, but got {0} instead".format(type(value)))

    def _get_password(self):
        """ 
        @return: the password used when authenticating with the bong.tv-API 
        @raise AttributeError: raised when the password is not set 
        """
        return getattr(self, "__password__")

    def _set_cookie(self, value):
        """ 
        sets the bong-tv-API cookie which is needed for authentication. Expects 
        a L{_Cookie} object, a string denoting a file path or cookie content,
        or a file-like object. 
        @raise TypeError: raised when the value's type is not suitable for creating a Cookie
        """
        if isinstance(value, _Cookie):
            cookie = value
        elif isinstance(value, file):
            cookie = _Cookie(value.read())
        elif isinstance(value, basestring):
            if os.path.isfile(value):
                cookie = _Cookie(open(value, mode="rt").read())
            else:
                cookie = _Cookie(value)
        else:
            raise TypeError()
        if isinstance(cookie, _Cookie):
            setattr(self, "__cookie__", cookie)
            with open(_COOKIE_PATH, mode="wt") as f:
                f.write(str(cookie))

    def _get_cookie(self):
        try:
            cookie = getattr(self, "__cookie__")
            assert isinstance(cookie, _Cookie), "Expected instance of {0}, but got {1} instead!".format(_Cookie, type(cookie))
            assert not cookie.is_expired(), "Cookie is expired"
        except (AttributeError, AssertionError):
            params = dict(login=self.username, password=self.password)
            connection = self._do_POST(BONGTVAPIv1_LOGIN_URL, params=params, with_cookie=False)
            response = connection.getresponse()
            if response.status in (httplib.OK, httplib.CREATED):
                # store cookie as instance variable *and* write it to disk
                self._set_cookie(response.getheader("Set-Cookie"))
            else:
                raise _make_exception_from_http_status_code(response.status, message=response.reason)
        return getattr(self, "__cookie__")

    username = property(fget=_get_username, fset=_set_username)
    password = property(fget=_get_password, fset=_set_password)
    cookie = property(fget=_get_cookie, fset=_set_cookie)

    def _make_http_headers(self, additional_headers, with_cookie=True):
        http_headers = {
            "User-Agent": "pybongtvapi/{0}".format(__version__),
            "Accept": "text/plain,application/json",
        }
        if type(additional_headers) is dict:
            http_headers.update(additional_headers)
        if with_cookie:
            http_headers.update({"Cookie": str(self.cookie)})
        return http_headers

    def _do_GET(self, url, params=None, host=BONGTVAPIv1_HOST, timeout=BONGTVAPIv1_TIMEOUT, with_cookie=True, http_headers=None):
        connection = httplib.HTTPConnection(host, timeout=timeout)
        query_string = "?{0}".format(urllib.urlencode(params)) if type(params) is dict else ""
        headers = self._make_http_headers(http_headers, with_cookie=with_cookie)
        connection.request("GET", url + query_string, headers=headers)
        return connection

    def _do_POST(self, url, params=None, host=BONGTVAPIv1_HOST, timeout=BONGTVAPIv1_TIMEOUT, with_cookie=True, http_headers=None):
        connection = httplib.HTTPConnection(host, timeout=timeout)
        body = urllib.urlencode(params) if type(params) is dict else None
        post_http_headers = {"Content-type": "application/x-www-form-urlencoded"}
        if type(http_headers) is dict:
            post_http_headers.update(http_headers)
        headers = self._make_http_headers(post_http_headers, with_cookie=with_cookie)
        connection.request("POST", url, body=body, headers=headers)
        return connection

    def _do_DELETE(self, url, params=None, host=BONGTVAPIv1_HOST, timeout=BONGTVAPIv1_TIMEOUT, with_cookie=True, http_headers=None):
        connection = httplib.HTTPConnection(host, timeout=timeout)
        body = urllib.urlencode(params) if type(params) is dict else None
        headers = self._make_http_headers(http_headers, with_cookie=with_cookie)
        connection.request("DELETE", url, body=body, headers=headers)
        return connection

    def _read_response(self, connection, response_handlers=None):
        if type(response_handlers) is not dict:
            on_ok = on_created = json.loads

            def on_not_found(r):
                raise IOError(json.loads(r).get("message", "Failed {0.status} {0.reason}".format(response)))

            response_handlers = {httplib.OK: on_ok, httplib.CREATED: on_created, httplib.NOT_FOUND: on_not_found}
        try:
            response = connection.getresponse()
            if response.status in response_handlers:
                result = response.read()
                response_handler = response_handlers[response.status]
                return response_handler(result) if callable(response_handler) else result
            else:
                raise _make_exception_from_http_status_code(response.status, message=response.reason)
        finally:
            connection.close()

    @delayed()
    def login(self):
        params = dict(login=self.username, password=self.password)
        connection = self._do_POST(BONGTVAPIv1_LOGIN_URL, params=params)
        return self._read_response(connection)

    @delayed()
    def list_user_recordings(self):
        connection = self._do_GET(BONGTVAPIv1_RECORDINGS_URL)
        return self._read_response(connection)["recordings"]

    @delayed()
    def create_recording(self, broadcast_id):
        params = dict(broadcast_id=int(broadcast_id))
        connection = self._do_POST(BONGTVAPIv1_RECORDINGS_URL, params=params)
        return self._read_response(connection)["recording"]

    @delayed()
    def delete_recording(self, recording_id):
        url = BONGTVAPIv1_RECORDING_URL_TEMPLATE.format(recording_id=int(recording_id))
        connection = self._do_DELETE(url)
        return self._read_response(connection, response_handlers={httplib.OK: None})

    @delayed()
    def get_list_of_channels(self):
        connection = self._do_GET(BONGTVAPIv1_CHANNELS_URL)
        return self._read_response(connection)["channels"]

    @delayed()
    def get_list_of_broadcasts(self, channel_id, date=None):
        date = time.strftime("%d-%m-%Y", time.localtime()) if (date is None) else date
        connection = self._do_GET(BONGTVAPIv1_BROADCASTS_URL, params=dict(channel_id=int(channel_id), date=date))
        return self._read_response(connection)["broadcasts"]

    @delayed()
    def get_broadcast_details(self, broadcast_id):
        url = BONGTVAPIv1_BROADCAST_URL_TEMPLATE.format(broadcast_id=int(broadcast_id))
        connection = self._do_GET(url)
        return self._read_response(connection)["broadcast"]

    @delayed()
    def search_broadcast(self, pattern):
        connection = self._do_GET(BONGTVAPIv1_BROADCAST_SEARCH_URL, params=dict(query=pattern))
        return self._read_response(connection)["broadcasts"]


class Broadcast(object):
    def __init__(self, broadcast_info, api):
        super(Broadcast, self).__init__()
        if not isinstance(api, API):
            raise TypeError()
        self.api = api
        self.broadcast_id = broadcast_info["id"]
        self.title = _sanitize(unicode(broadcast_info.get("title") or u"").encode("utf-8"))
        self.subtitle = _sanitize(unicode(broadcast_info.get("subtitle") or u"").encode("utf-8"))
        self.production_year = broadcast_info["production_year"]
        self.starts_at = time.localtime(broadcast_info["starts_at_ms"])
        self.ends_at = time.localtime(broadcast_info["ends_at_ms"])
        self.duration_in_secs = broadcast_info["ends_at_ms"] - broadcast_info["starts_at_ms"]
        self.duration = int(self.duration_in_secs / 60.)
        self.country = _sanitize(unicode(broadcast_info.get("country") or u"").encode("utf-8"))
        thumb_url_path = unicode((broadcast_info.get("image") or {}).get("href") or u"").encode("utf-8")
        self.thumb_url = ("http://" + BONGTVAPIv1_HOST + thumb_url_path) if thumb_url_path else ""
        self.channel_id = broadcast_info["channel_id"]
        self.channel_logo_url = "http://{host}/images/channel/b/{channel_id}.png".format(host=BONGTVAPIv1_HOST, channel_id=self.channel_id)
        self.season = int((broadcast_info.get("serie") or {}).get("season") or 0)
        self.episode = int((broadcast_info.get("serie") or {}).get("episode") or 0)
        self.total_episodes = int((broadcast_info.get("serie") or {}).get("total_episodes") or 0)
        # FIXME categories is a tree-like structure
        self.categories = set(_sanitize(unicode(category.get("name") or u"").encode("utf-8")) for category in broadcast_info["categories"] if category.get("name"))
        self.outline = _sanitize(unicode(broadcast_info.get("short_text") or u"").encode("utf-8"))
        self.hd = True if broadcast_info.get("hd") else False
        self.channel_name = _sanitize(unicode(broadcast_info.get("channel_name") or u"").encode("utf-8"))

    @property
    def broadcast_details(self):
        if not hasattr(self, "__broadcast_details__"):
            broadcast_details = self.api.get_broadcast_details(self.broadcast_id)
            setattr(self, "__broadcast_details__", broadcast_details)
        return getattr(self, "__broadcast_details__")

    @property
    def rating(self):
        return self.broadcast_details["rating"]

    @property
    def votes(self):
        return self.broadcast_details["votes"]

    @property
    def plot(self):
        return _sanitize(unicode(self.broadcast_details.get("long_text") or u"").encode("utf-8"))

    @property
    def hint(self):
        return _sanitize(unicode(self.broadcast_details.get("hint_text") or u"").encode("utf-8"))

    @property
    def directors(self):
        return sorted(
            set(_sanitize(unicode(director.get("name") or u"").encode("utf-8")) for director in itertools.chain(*[role["people"] for role in self.broadcast_details["roles"] if role["name"] == "Regisseur"]) if director.get("name")))

    @property
    def composers(self):
        return sorted(set(_sanitize(unicode(composer.get("name") or u"").encode("utf-8")) for composer in itertools.chain(*[role["people"] for role in self.broadcast_details["roles"] if role["name"] == "Musik"]) if composer.get("name")))

    @property
    def authors(self):
        return sorted(set(_sanitize(unicode(author.get("name") or u"").encode("utf-8")) for author in itertools.chain(*[role["people"] for role in self.broadcast_details["roles"] if role["name"] == "Autor"]) if author.get("name")))

    @property
    def actors(self):
        return sorted(set(
            Actor(_sanitize(unicode(actor.get("name") or u"").encode("utf-8")), _sanitize(unicode(actor.get("role") or u"").encode("utf-8"))) for actor in
            itertools.chain(*[role["people"] for role in self.broadcast_details["roles"] if role["name"] == "Schauspieler"]) if actor.get("name")))

    def is_tvshow(self):
        return any([
            (self.season > 0) and (self.episode > 0),
            WELL_KNOWN_TVSHOW_TITLES_REGEX.match(self.title) if WELL_KNOWN_TVSHOW_TITLES_REGEX is not None else False,
        ])

    def create_recording(self):
        return Recording(self.api.create_recording(self.broadcast_id), self.api)


class Recording(object):
    def __init__(self, recording_data, api):
        super(Recording, self).__init__()
        if not isinstance(api, API):
            raise TypeError("Expected type {0}, got {1} instead!".format(API, type(api)))
        self.api = api
        self.status = recording_data["status"]
        self.quality = recording_data["quality"]
        self.recording_id = recording_data["id"]
        self.urls = dict((file_data["quality"].upper(), file_data["href"].encode("utf-8")) for file_data in recording_data["files"])
        self.broadcast = Broadcast(recording_data["broadcast"], api)
        # delegates
        self.is_tvshow = self.broadcast.is_tvshow
        self.actors = self.broadcast.actors
        self.authors = self.broadcast.authors
        self.broadcast_id = self.broadcast.broadcast_id
        self.categories = self.broadcast.categories
        self.channel_id = self.broadcast.channel_id
        self.channel_logo_url = self.broadcast.channel_logo_url
        self.channel_name = self.broadcast.channel_name
        self.composers = self.broadcast.composers
        self.country = self.broadcast.country
        self.directors = self.broadcast.directors
        self.duration = self.broadcast.duration
        self.duration_in_secs = self.broadcast.duration_in_secs
        self.ends_at = self.broadcast.ends_at
        self.episode = self.broadcast.episode
        self.hint = self.broadcast.hint
        self.outline = self.broadcast.outline
        self.plot = self.broadcast.plot
        self.production_year = self.broadcast.production_year
        self.rating = self.broadcast.rating
        self.season = self.broadcast.season
        self.starts_at = self.broadcast.starts_at
        self.subtitle = self.broadcast.subtitle
        self.thumb_url = self.broadcast.thumb_url
        self.title = self.broadcast.title
        self.total_episodes = self.broadcast.total_episodes
        self.votes = self.broadcast.votes

    @property
    def url(self):
        return self.get_url()

    def is_recorded(self):
        return self.status == "recorded"

    def is_scheduled(self):
        return self.status == "queued"

    def get_url(self, preferred_qualities=None):
        """ finds a download url which matches the recording's quality. raises an
        IOError if no such url is found *and* the recording is supposed to be recorded.
        Returns None when the recording is not yet recorded.
        """

        def transform_preferred_qualities(qualities):
            if qualities is None:
                qualities = ["NQ", "HQ", "HD"]
            if isinstance(qualities, basestring):
                if "," in qualities:
                    qualities = qualities.split(",")
                elif " " in qualities:
                    qualities = qualities.split()
                else:
                    qualities = (qualities,)
            return tuple(qualities)

        # 1=nq, 2=hq, 3=nq+hq, 6=hq+hd, 7=nq+hq+hd
        url = None
        if self.urls:
            if self.quality == 1 and "NQ" in self.urls:
                url = self.urls.get("NQ")
            elif self.quality == 2 and "HQ" in self.urls:
                return self.urls.get("HQ")
            elif self.quality in (3, 6, 7):
                for preferred_quality in transform_preferred_qualities(preferred_qualities):
                    if preferred_quality in self.urls:
                        return self.urls.get(preferred_quality)
        if url is None and self.is_recorded():
            raise IOError("No url found!")
        return url

    def delete_recording(self):
        self.api.delete_recording(self.recording_id)


class BongSpace(object):
    def __init__(self, api):
        super(BongSpace, self).__init__()
        if not isinstance(api, API):
            raise TypeError("Expected type {0}, but got {1} instead!".format(API, type(api)))
        self.api = api

    @property
    def used_capacity(self):
        used_cap = self.api.login().get("subscription", {}).get("usedcap")
        if used_cap is None:
            raise IOError("Cannot find used capacity!")
        return used_cap

    @property
    def max_capacity(self):
        max_cap = self.api.login().get("subscription", {}).get("maxcap")
        if max_cap is None:
            raise IOError("Cannot find max capacity!")
        return max_cap

    @property
    def used_space_percentage(self):
        used_space_percentage = self.api.login().get("subscription", {}).get("used_space_percent")
        if used_space_percentage is None:
            raise IOError("Cannot find used space percentage!")
        if 0 <= int(used_space_percentage) <= 100:
            return int(used_space_percentage)
        else:
            raise ValueError("Invalid range for used_space_percentage: 0 <= {0} <= 100".format(used_space_percentage))

    @property
    def recordings(self):
        return sorted([Recording(recording, self.api) for recording in self.api.list_user_recordings()], key=operator.attrgetter("starts_at"))

    def create_recording(self, broadcast_id):
        return Recording(self.api.create_recording(int(broadcast_id)), self.api)

    def get_recording(self, recording_id):
        recordings = [recording for recording in self.recordings if recording.recording_id == int(recording_id)]
        if len(recordings):
            return recordings[0]

    def delete_recording(self, recording_id):
        recording = self.get_recording(int(recording_id))
        if recording:
            self.api.delete_recording(int(recording_id))


class Channel(object):
    def __init__(self, channel_info, api, epg_offset=7):
        super(Channel, self).__init__()
        if not isinstance(api, API):
            raise TypeError("Expected type {0}, got {1} instead!".format(API, type(api)))
        self.api = api
        self.channel_id = channel_info["id"]
        self.logo_url = "http://{host}/images/channel/b/{channel_id}.png".format(host=BONGTVAPIv1_HOST, channel_id=self.channel_id)
        self.name = _sanitize(unicode(channel_info.get("name") or u"").encode("UTF-8"))
        self.recordable = channel_info["recordable"]
        self.position = channel_info["position"]
        self.hd = channel_info["hd"]
        self.epg_offset = epg_offset

    def is_hd(self):
        return bool(self.hd)

    def get_broadcasts_per_day(self, offset=0):
        """
        Returns a list of broadcasts per day
        @param offset: the day offset. 0=today, 1=tomorrow, 2=day after tomorrow and so on ..
        """
        local_time = time.localtime(time.time() + (int(offset) * 3600 * 24))
        date = time.strftime("%d-%m-%Y", local_time)
        broadcasts = sorted([Broadcast(broadcast, self.api) for broadcast in self.api.get_list_of_broadcasts(self.channel_id, date=date)],key=operator.attrgetter("starts_at"))
        now = time.localtime()
        return [broadcast for broadcast in broadcasts if broadcast.starts_at >= now]

    @property
    def broadcasts(self):
        broadcasts = sorted(itertools.chain(*[self.get_broadcasts_per_day(offset=offset) for offset in xrange(0, self.epg_offset)]), key=operator.attrgetter("starts_at"))
        now = time.localtime()
        return [broadcast for broadcast in broadcasts if broadcast.starts_at >= now]


class BongGuide(object):
    def __init__(self, api):
        super(BongGuide, self).__init__()
        if not isinstance(api, API):
            raise TypeError("Expected type {0}, but got {1} instead!".format(API, type(api)))
        self.api = api

    @property
    def channels(self):
        return sorted([Channel(channel, self.api) for channel in self.api.get_list_of_channels()], key=operator.attrgetter("position"))

    def get_channel(self, channel_id):
        channels = [candidate for candidate in self.channels if candidate.channel_id == int(channel_id)]
        if len(channels):
            return channels[0]

    def search_broadcast(self, search_pattern):
        for broadcast in self.api.search_broadcast(search_pattern):
            yield Broadcast(broadcast, self.api)

    def search_broadcast_per_channel(self, search_pattern, channel):
        channel_id = None
        if type(channel) is int:
            channel_id = channel
        elif isinstance(channel, Channel):
            channel_id = channel.channel_id
        elif isinstance(channel, basestring):
            candidates = [candidate for candidate in self.channels if candidate.name == channel]
            if candidates:
                channel_id = candidates[0].channel_id
        if channel_id is None:
            raise IOError("Cannot find appropriate channel")
        for broadcast in self.search_broadcast(search_pattern):
            if broadcast.channel_id == channel_id:
                yield broadcast

# aliases
EPG = BongGuide
PVR = BongSpace

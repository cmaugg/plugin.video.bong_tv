#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import os

import xbmcswift2
from xbmcswift2 import actions
from xbmcswift2 import xbmc, xbmcgui
from lib import pybongtvapi


plugin = xbmcswift2.Plugin()
addon_icon = plugin._addon.getAddonInfo("icon")

pybongtvapi.COOKIE_PATH = os.path.join(os.path.dirname(plugin.storage_path), "..", ".pybongtvapi.session-cookie")

CONTENT_TYPES = VIDEOS, EPISODES, MOVIES = "videos", "episodes", "movies"


def tr(string_id, **kw):
    return plugin.get_string(int(string_id)).encode("utf-8").format(**kw)


def redirect(url):
    xbmc.executebuiltin(actions.update_view(url))


def on_authentication_error(yeslabel=None, nolabel=None, url=None):
    if xbmcgui.Dialog().yesno(tr(30018), tr(30019), line3=tr(30020), yeslabel=yeslabel or '', nolabel=nolabel or ''):
        if os.path.isfile(pybongtvapi.COOKIE_PATH):
            os.remove(pybongtvapi.COOKIE_PATH)
        plugin.open_settings()
        if url:
            redirect(url)


class Settings(object):
    @property
    def content_type(self):
        return plugin.get_setting("content_type", converter=str)

    @property
    def force_content_type(self):
        return plugin.get_setting("force_content_type", converter=bool)

    @property
    def view_mode_id(self):
        return plugin.get_setting("view_mode_id", converter=int)

    @property
    def force_view_mode(self):
        return plugin.get_setting("force_view_mode", converter=bool)

    @property
    def use_thumb_as_fanart(self):
        return plugin.get_setting("use_thumb_as_fanart", converter=bool)

    @property
    def cache_thumbs_locally(self):
        return plugin.get_setting("cache_thumbs_locally", converter=bool)

    @property
    def username(self):
        # when username is not set, then 'foo' will trigger an authentication error, and
        # user is prompted to re-enter his username
        return plugin.get_setting("username", converter=str) or 'foo'

    @property
    def password(self):
        # when password is not set, then 'foo' will trigger an authentication error, and
        # user is prompted to re-enter his password
        return plugin.get_setting("password", converter=str) or 'foo'

    @property
    def preferred_qualities(self):
        return plugin.get_setting("preferred_qualities", converter=str).split("+")

    @property
    def use_extended_broadcast_details(self):
        return plugin.get_setting('use_extended_broadcast_details', converter=bool)


class API(object):
    @property
    def api(self):
        return pybongtvapi.API(Settings().username, Settings().password)

    @property
    def epg(self):
        return pybongtvapi.EPG(self.api)

    @property
    def pvr(self):
        return pybongtvapi.PVR(self.api)


def get_broadcasts(channel_id, offset=0):
    channel_id = int(channel_id)
    offset = int(offset)
    channel = API().epg.get_channel(channel_id)
    return tuple(channel.get_broadcasts(offset=offset))


def get_broadcast_details(broadcast):
    metadata = dict(
        genre=", ".join(broadcast.categories),
        year=broadcast.production_year,
        episode=broadcast.episode,
        season=broadcast.season,
        plot=broadcast.outline,
        plotoutline=broadcast.outline,
        title=broadcast.subtitle if broadcast.is_tvshow() else broadcast.title,
        duration=broadcast.duration,
        tagline=broadcast.subtitle,
        tvshowtitle=broadcast.title if broadcast.is_tvshow() else broadcast.title,
        aired=time.strftime("%Y-%m-%d", broadcast.starts_at),
    )
    if Settings().use_extended_broadcast_details:
        expensive_metadata = dict(
            rating=broadcast.rating,
            director=", ".join(broadcast.directors),
            cast=", ".join("{0.name}".format(actor) for actor in broadcast.actors),
            castandrole=", ".join("{0.name}|{0.role}".format(actor) for actor in broadcast.actors),
            writer=", ".join(broadcast.authors),
            plot=broadcast.plot or broadcast.hint,
            votes=broadcast.votes,
        )
        metadata.update(expensive_metadata)
    return metadata


def new_image_url(url, timeout=None, default="DefaultVideo.png"):
    if url:
        thumbs_dir = os.path.join(os.path.dirname(plugin.storage_path), "..", "thumbs")
        if not os.path.isdir(thumbs_dir):
            os.makedirs(thumbs_dir)
        new_url = os.path.join(thumbs_dir, "thumb-{0}.jpg".format(hash(url)))
        if os.path.isfile(new_url):
            return new_url
        elif Settings().cache_thumbs_locally:
            import httplib, urlparse

            (_, netloc, path, _, _) = urlparse.urlsplit(url)
            conn = httplib.HTTPConnection(netloc, timeout=timeout)
            try:
                conn.request("GET", path)
                response = conn.getresponse()
                if response.status == 200:
                    if response.getheader("Content-Length"):
                        return url
                    else:
                        plugin.log.warning("No Content-Length header returned for image url '{0}', caching image on disk to '{1}' ..".format(url, new_url))
                        with open(new_url, mode="wb") as f:
                            while True:
                                data = response.read(2048)
                                if data:
                                    f.write(data)
                                else:
                                    break
                        return new_url
                raise IOError("Cannot load image, HTTP response code={0.status} {0.reason}".format(response))
            except Exception, error:
                plugin.log.error("Cannot load image from '{0}': {1}".format(url, error))
            finally:
                conn.close()
    # in any other case, return an empty string as url, indicating that there is no image url
    return default


def make_broadcast_title(broadcast, title_prefix=None, with_starts_at=True):
    def produce():
        if title_prefix:
            yield title_prefix
            yield ': '
        if with_starts_at:
            yield '{0.starts_at.tm_mday:0>2}.{0.starts_at.tm_mon:0>2}, {0.starts_at.tm_hour:0>2}:{0.starts_at.tm_min:0>2}'.format(broadcast)
            yield ' - '
        yield '{0.title}: {0.subtitle}'.format(broadcast) if broadcast.subtitle else broadcast.title

    return ''.join(produce())


def make_list_item(broadcast, path, is_playable=False, thumb_url=None, bg_image_url=None, context_menu=None, replace_context_menu=False, title_prefix=None):
    properties = dict()
    thumb_url = thumb_url or new_image_url(broadcast.thumb_url)
    if Settings().use_thumb_as_fanart:
        properties.update(fanart_image=thumb_url)
    elif bg_image_url:
        properties.update(fanart_image=bg_image_url or thumb_url)
    return dict(label=make_broadcast_title(broadcast, title_prefix=title_prefix), label2=broadcast.subtitle, icon=thumb_url, thumbnail=thumb_url, path=path, is_playable=is_playable, properties=properties, context_menu=context_menu,
                replace_context_menu=replace_context_menu, info_type="video", info=get_broadcast_details(broadcast))


def finish(items, sort_methods=None, succeeded=True, update_listing=False, cache_to_disc=True, view_mode=None, content_type=None):
    applied_content_type = content_type if isinstance(content_type, basestring) else (Settings().content_type if Settings().force_content_type else VIDEOS)
    if applied_content_type:
        plugin.set_content(applied_content_type)
    applied_view_mode = view_mode if isinstance(view_mode, int) else (Settings().view_mode_id if Settings().force_view_mode else None)
    return plugin.finish(items, sort_methods=sort_methods, succeeded=succeeded, update_listing=update_listing, cache_to_disc=cache_to_disc, view_mode=applied_view_mode)


@plugin.route("/action/create-recording/<broadcast_id>")
def action_create_recording(broadcast_id):
    try:
        recording = API().pvr.create_recording(int(broadcast_id))
        assert recording is not None
    except pybongtvapi.CannotCreateRecordingError:
        if xbmcgui.Dialog().yesno(tr(30601), tr(30602), tr(30604), yeslabel=tr(30605), nolabel=tr(30606)):
            redirect(plugin.url_for('view_recordings'))
    except (pybongtvapi.Error, AssertionError):
        xbmcgui.Dialog().ok(tr(30601), tr(30603))
    else:
        title = make_broadcast_title(recording, with_starts_at=False)
        plugin.notify(tr(30600, title=title), image=addon_icon)


@plugin.route("/action/delete-recording/<recording_id>/<recording_title>")
def action_delete_recording(recording_id, recording_title):
    if xbmcgui.Dialog().yesno(tr(30700), tr(30701, title=recording_title)):
        API().pvr.delete_recording(int(recording_id))
        redirect(plugin.url_for('view_recordings'))
        plugin.notify(tr(30702, title=recording_title), image=addon_icon)


@plugin.route("/")
def view_index():
    items = [
        dict(label=tr(30100), icon="DefaultMovies.png", thumbnail="DefaultMovies.png", path=plugin.url_for("view_recordings")),
        dict(label=tr(30101), icon="DefaultTVShows.png", thumbnail="DefaultTVShows.png", path=plugin.url_for("view_channels")),
        dict(label=tr(30102), icon="DefaultVideoPlugins.png", thumbnail="DefaultVideoPlugins.png", path=plugin.url_for("view_search_epg")),
    ]
    return finish(items, content_type=VIDEOS)


@plugin.route("/view/recordings")
def view_recordings():
    def produce_items():
        for recording in API().pvr.recordings:
            delete_recording_url = plugin.url_for("action_delete_recording", recording_id=recording.recording_id, recording_title=make_broadcast_title(recording, with_starts_at=False))
            context_menu = [
                [tr(30200), actions.update_view(plugin.url_for("view_recordings"))],
                [tr(30201), actions.background(delete_recording_url)],
            ]
            if recording.is_recorded():
                path = recording.get_url(preferred_qualities=Settings().preferred_qualities)
                is_playable = True
                title_prefix = None
            else:
                path = delete_recording_url
                is_playable = False
                title_prefix = tr(30202)
            yield make_list_item(recording, path, is_playable=is_playable, context_menu=context_menu, title_prefix=title_prefix)

    try:
        items = tuple(produce_items())
    except pybongtvapi.AuthenticationError:
        on_authentication_error(url=plugin.url_for('view_recordings'))
    else:
        return finish(items, content_type=EPISODES)


@plugin.route("/view/channels")
def view_channels():
    def produce_items():
        for channel in API().epg.channels:
            path = plugin.url_for("view_broadcasts_per_channel", channel_id=channel.channel_id, offset=0)
            yield dict(label=channel.name, icon=channel.logo_url, thumbnail=channel.logo_url, path=path)

    try:
        items = tuple(produce_items())
    except pybongtvapi.AuthenticationError:
        on_authentication_error(url=plugin.url_for('view_channels'))
    else:
        return finish(items, content_type=VIDEOS)


@plugin.route("/view/search-epg")
def view_search_epg():
    def produce_items():
        search_pattern = plugin.keyboard(heading="Search broadcast")
        for broadcast in API().epg.search_broadcast(search_pattern):
            path = plugin.url_for("action_create_recording", broadcast_id=broadcast.broadcast_id)
            yield make_list_item(broadcast, path, bg_image_url=broadcast.channel_logo_url)

    try:
        items = tuple(produce_items())
    except pybongtvapi.AuthenticationError:
        on_authentication_error(url=plugin.url_for('view_search_epg'))
    return finish(items, content_type=EPISODES)


@plugin.route("/view/broadcasts-per-channel/<channel_id>/<offset>")
def view_broadcasts_per_channel(channel_id, offset=0):
    def produce_items():
        channel = API().epg.get_channel(channel_id)
        for broadcast in channel.get_broadcasts_per_day(offset=int(offset)):
            path = plugin.url_for("action_create_recording", broadcast_id=broadcast.broadcast_id)
            yield make_list_item(broadcast, path, bg_image_url=channel.logo_url)
        url_for_next_days_broadcasts = plugin.url_for("view_broadcasts_per_channel", channel_id=int(channel_id), offset=int(offset) + 1)
        yield dict(label=tr(30500), icon="DefaultMovies.png", thumbnail="DefaultMovies.png", path=url_for_next_days_broadcasts)

    items = tuple(produce_items())
    finish(items, content_type=EPISODES)


if __name__ == "__main__":
    plugin.run()

#!/usr/bin/env python
# -*- coding: utf-8 -*-


from xbmcswift2 import xbmc
from xbmcswift2 import xbmcgui

import functools
import operator
import os
import sys
import time
import xbmcswift2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'resources', 'lib'))

import pybongtvapi

plugin = xbmcswift2.Plugin()
addon_icon = plugin.addon.getAddonInfo('icon')
addon_name = plugin.addon.getAddonInfo('name')

pybongtvapi.DEFAULT_COOKIE_DIR = os.path.join(plugin.storage_path, '..', '.pybongtvapi', 'cookies')

CONTENT_TYPES = VIDEOS, EPISODES, MOVIES = 'videos', 'episodes', 'movies'

# xbmc translation identifiers
# the addon's translation identifiers
TR_AUTHORIZATION_ERROR = 30000  # en: Authorization Error! de: Anmeldung fehlgeschlagen!
TR_UPDATE_CREDENTIALS = 30001 # en: Please update your BONG.TV username and password, de: Bitte bong.tv-Benutzernamen und -Passwort aktualisieren
TR_BONGSPACE = 30002  # en: BongSpace de: BongSpace
TR_BONGGUIDE = 30003  # en: BongGuide de: BongGuide
TR_SEARCH_BROADCASTS = 30004  # en: Search broadcasts de: Suche Sendungen
TR_X_BROADCASTS_RECORDED = 30005  # en: {0} broadcasts recorded de: {0} Sendungen aufgenommen
TR_MANAGE_X_BROADCASTS = 30006  # en: Manage {0} broadcasts de: {0} Sendungen verwalten
TR_NO_RECORDINGS_FOUND = 30007  # en: No recordings found! de: Keine Aufnahmen gefunden!
TR_TITLE_DELETE_RECORDING = 30008  # en: Delete Recording? de: Aufnahme löschen?
TR_DELETE_RECORDING = 30009  # en: Delete recording "{0}"? de: Aufnahme "{0}" löschen?
TR_CANNOT_DELETE_RECORDING = 30010  # en: Cannot delete recording "{0}"! de: "{0}" kann nicht gelöscht werden!
TR_RECORDING_DELETED = 30011  # en: "{0}" deleted successfully. de: "{0}" erfolgreich gelöscht.
TR_TITLE_RECORD_BROADCAST = 30012  # en: Record broadcast? de: Aufnahme tätigen?
TR_RECORD_BROADCAST = 30013  # en: Record broadcast "{0}"? de: Sendung "{0}" aufzeichnen?
TR_CANNOT_RECORD_BROADCAST = 30014  # en: Cannot record broadcast "{0}"! de: "{0}" kann nicht aufgezeichnet werden!
TR_WILL_RECORD_BROADCAST = 30015  # en: "{0}" is scheduled for recording de: "{0}" wird aufgezeichnet
TR_NEXT_DAYS_BROADCASTS = 30016  # en: Broadcasts from {0} de: Sendungen vom {0}
TR_PREVIOUS_DAYS_BROADCASTS = 30017  # en: Broadcasts from {0} de: Sendungen vom {0}
TR_LIST_OF_BROADCASTS = 30018  # en: List of channels de: Senderliste
TR_TITLE_SEARCH_MATCHING_BROADCASTS = 30019  # en: Search broadcasts de: Suche Sendungen
TR_X_MATCHING_BROADCASTS_FOUND = 30020 # en: Found {0} matching broadcasts for search term "{1}" de: {0} passende Sendungen für den Suchbegriff "{1}" gefunden
TR_NO_MATCHING_BROADCASTS_FOUND = 30021  # en: No matching broadcasts found for search term "{0}" de: Keine passenden Sendungen für den Suchbegriff "{0}" gefunden!


# xbmc utils/helpers
def get_view_mode_id():
    if plugin.get_setting('force_view_mode', converter=bool):
        return plugin.get_setting('view_mode_id', converter=int)


def get_content_type():
    if plugin.get_setting('force_content_type', converter=bool):
        return plugin.get_setting('content_type', converter=str)


def use_extended_broadcast_details():
    return plugin.get_setting('use_extended_broadcast_details', converter=bool)


def normalize_title(broadcast, include_time=True, include_channel_name=False):
    label = ('{0.title}: {0.subtitle}'.format(broadcast) if broadcast.is_tvshow() else broadcast.title)
    if include_time:
        label = time.strftime('%d.%m, %H:%M: ', broadcast.starts_at) + label
    if include_channel_name:
        label = (broadcast.channel_name + (', ' if include_time else ': ') + label)
    return label


def new_broadcast_item(broadcast, path=None, include_time=True, include_channel_name=False):
    label = normalize_title(broadcast, include_time=include_time, include_channel_name=include_channel_name)
    broadcast_details = dict(
        genre=', '.join(broadcast.categories),
        year=broadcast.production_year,
        episode=broadcast.episode,
        season=broadcast.season,
        plot=broadcast.plot if use_extended_broadcast_details() else broadcast.outline,
        plotoutline=broadcast.outline,
        title=broadcast.subtitle if broadcast.is_tvshow() else broadcast.title,
        duration=broadcast.duration,
        tagline=broadcast.subtitle,
        tvshowtitle=broadcast.title if broadcast.is_tvshow() else None,
        aired=time.strftime('%Y-%m-%d', broadcast.starts_at),
    )
    properties = dict(fanart_image=broadcast.thumb_url)
    return dict(label=label, label2=broadcast.subtitle, icon=broadcast.channel_logo_url, thumbnail=broadcast.thumb_url,
                path=path, properties=properties, info=broadcast_details, info_type='video')


def new_recording_item(recording, path=None, include_time=True, include_channel_name=False):
    item = new_broadcast_item(recording, path=path, include_time=include_time,
                              include_channel_name=include_channel_name)
    if recording.is_recorded() and path is None:
        item.update(is_playable=True, path=recording.url)
    elif recording.is_recorded() and path is not None:
        item.update(label=' * ' + item['label'])
    return item


def new_channel_item(channel, path):
    return dict(label=channel.name, icon=channel.logo_url, thumbnail=channel.logo_url, path=path, info_type='video')


def finish(items, content_type=None, view_mode_id=None):
    if content_type in CONTENT_TYPES or get_content_type():
        plugin.set_content(content_type if content_type in CONTENT_TYPES else get_content_type())
    return plugin.finish(items, view_mode=view_mode_id or get_view_mode_id())


def notify(msg):
    if msg and isinstance(msg, basestring):
        xbmc.executebuiltin('Notification("' + addon_name + '", "' + msg + '", "5000", "' + addon_icon + '")')


def refresh_view(msg=None):
    if msg and isinstance(msg, basestring):
        notify(msg)
    xbmc.executebuiltin('Container.Refresh')


def update_view(url, msg=None):
    if not isinstance(url, basestring):
        raise TypeError()
    if msg and isinstance(msg, basestring):
        notify(msg)
    xbmc.executebuiltin('Container.Update(' + url + ')')


def tr(msg_id, *a, **kw):
    return (plugin.get_string(int(msg_id)) or '').encode('utf-8').format(*a, **kw)


# bong.tv utils/helpers
def new_api():
    return pybongtvapi.API(credentials=pybongtvapi.UserCredentials(plugin.get_setting('username'),
                                                                   plugin.get_setting('password')))


def new_epg():
    return pybongtvapi.EPG(new_api())


def new_pvr():
    return pybongtvapi.PVR(new_api())


def requires_authorization(wrapped):
    def wrapper(*a, **kw):
        for _ in range(3):
            try:
                return wrapped(*a, **kw)
            except pybongtvapi.AuthorizationError:
                xbmcgui.Dialog().ok(tr(TR_AUTHORIZATION_ERROR), tr(TR_UPDATE_CREDENTIALS))
                plugin.open_settings()

    return functools.update_wrapper(wrapper, wrapped)


@requires_authorization
def get_recordings():
    return new_pvr().recordings


@requires_authorization
def get_channels():
    return new_epg().channels


@requires_authorization
def get_channel(channel_id):
    return new_epg().get_channel(channel_id)


# addon routing
@plugin.route('/')
def page_index():
    items = [
        dict(label=tr(TR_BONGSPACE), path=plugin.url_for('page_pvr')),
        dict(label=tr(TR_BONGGUIDE), path=plugin.url_for('page_epg')),
        dict(label=tr(TR_SEARCH_BROADCASTS), path=plugin.url_for('page_search')),
    ]
    return finish(items)


@plugin.route('/pvr')
def page_pvr():
    def producer():
        if recorded:
            yield dict(label=tr(TR_X_BROADCASTS_RECORDED, len(recorded)), path=plugin.url_for('page_pvr_recorded'))
        yield dict(label=tr(TR_MANAGE_X_BROADCASTS, len(recordings)), path=plugin.url_for('page_pvr_manage'))

    recordings = sorted(get_recordings(), key=operator.attrgetter('starts_at'))
    recorded = [recording for recording in recordings if recording.is_recorded()]
    if recordings:
        return finish(tuple(producer()))
    else:
        update_view(plugin.url_for('page_index'), msg=tr(TR_NO_RECORDINGS_FOUND))


@plugin.route('/pvr/recorded')
def page_pvr_recorded():
    def producer():
        for recorded_recording in recorded:
            yield new_recording_item(recorded_recording)

    recordings = sorted(get_recordings(), key=operator.attrgetter('starts_at'))
    recorded = [recording for recording in recordings if recording.is_recorded()]
    if recorded:
        return finish(tuple(producer()), content_type='movies', view_mode_id=504)
    else:
        update_view(plugin.url_for('page_pvr'), msg=tr(TR_NO_RECORDINGS_FOUND))


@plugin.route('/pvr/manage')
def page_pvr_manage():
    def producer():
        for recording in recordings:
            path = plugin.url_for('action_delete_recording', recording_id=recording.recording_id,
                                  recording_title=normalize_title(recording, include_time=False))
            yield new_recording_item(recording, path=path, include_channel_name=True)

    recordings = sorted(get_recordings(), key=operator.attrgetter('starts_at'))
    if recordings:
        return finish(tuple(producer()), content_type='movies', view_mode_id=504)
    else:
        update_view(plugin.url_for('page_pvr'), msg=tr(TR_NO_RECORDINGS_FOUND))


@plugin.route('/action/delete-recording/<recording_id>/<recording_title>')
def action_delete_recording(recording_id, recording_title):
    if xbmcgui.Dialog().yesno(tr(TR_TITLE_DELETE_RECORDING), tr(TR_DELETE_RECORDING, recording_title)):
        try:
            new_pvr().delete_recording(int(recording_id))
        except pybongtvapi.Error:
            refresh_view(msg=tr(TR_CANNOT_DELETE_RECORDING, recording_title))
        else:
            refresh_view(msg=tr(TR_RECORDING_DELETED, recording_title))


@plugin.route('/action/create-recording/<broadcast_id>/<broadcast_title>')
def action_create_recording(broadcast_id, broadcast_title):
    if xbmcgui.Dialog().yesno(tr(TR_TITLE_RECORD_BROADCAST), tr(TR_RECORD_BROADCAST, broadcast_title)):
        try:
            recording = new_pvr().create_recording(int(broadcast_id))
            assert isinstance(recording, pybongtvapi.Recording)
        except (pybongtvapi.Error, AssertionError):
            refresh_view(msg=tr(TR_CANNOT_RECORD_BROADCAST, broadcast_title))
        else:
            notify(tr(TR_WILL_RECORD_BROADCAST, broadcast_title))

@plugin.route('/epg')
def page_epg():
    def producer():
        for channel in get_channels():
            yield new_channel_item(channel, path=plugin.url_for('page_epg_channel', channel_id=channel.channel_id,
                                                                offset=0))
    items = tuple(producer())
    return finish(items)


@plugin.route('/epg/<channel_id>/<offset>')
def page_epg_channel(channel_id, offset):
    def producer():
        channel = get_channel(channel_id)
        broadcasts = channel.get_broadcasts_per_day(offset=int(offset))
        for broadcast in broadcasts:
            path = plugin.url_for('action_create_recording', broadcast_id=broadcast.broadcast_id,
                                  broadcast_title=normalize_title(broadcast, include_time=False))
            yield new_broadcast_item(broadcast, path=path)
        if broadcasts:
            time.time() + (int(offset) + 1)
            next_day = time.strftime('%d.%m.', time.localtime(time.time() + ((int(offset) + 1) * 3600 * 24)))
            next_day_label = tr(TR_NEXT_DAYS_BROADCASTS, next_day)
            yield dict(label=next_day_label, path=plugin.url_for('page_epg_channel', channel_id=channel_id,
                                                                 offset=int(offset) + 1))
        if int(offset) >= 1:
            time.time() + (int(offset) + 1)
            previous_day = time.strftime('%d.%m.', time.localtime(time.time() + ((int(offset) - 1) * 3600 * 24)))
            previous_day_label = tr(TR_PREVIOUS_DAYS_BROADCASTS, previous_day)
            yield dict(label=previous_day_label, path=plugin.url_for('page_epg_channel', channel_id=channel_id,
                                                                     offset=int(offset) - 1))
        yield dict(label=tr(TR_LIST_OF_BROADCASTS), path=plugin.url_for('page_epg'))
    items = tuple(producer())
    return finish(items, content_type=MOVIES)

@plugin.route('/search')
def page_search():
    def producer():
        for broadcast in new_epg().search_broadcasts(search_pattern):
            path = plugin.url_for('action_create_recording', broadcast_id=broadcast.broadcast_id,
                                  broadcast_title=normalize_title(broadcast, include_time=True,
                                                                  include_channel_name=True))
            yield new_broadcast_item(broadcast, path=path, include_time=True, include_channel_name=True)

    search_pattern = (plugin.keyboard(heading=tr(TR_TITLE_SEARCH_MATCHING_BROADCASTS)) or '').strip()
    if search_pattern:
        items = tuple(producer())
        if items:
            notify(tr(TR_X_MATCHING_BROADCASTS_FOUND, len(items), search_pattern))
            return finish(items, content_type='movies', view_mode_id=504)
        else:
            refresh_view(msg=tr(TR_NO_MATCHING_BROADCASTS_FOUND, search_pattern))


if __name__ == '__main__':
    plugin.run()

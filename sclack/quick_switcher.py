import urwid
import time
import unicodedata
import itertools
from collections import defaultdict
from .store import Store
from sclack.components import get_icon
from sclack.utils.lookups import PartialMatchLookup, PartialMatchList


def remove_diacritic(input):
    '''
    Accept a unicode string, and return a normal string (bytes in Python 3)
    without any diacritical marks.
    '''
    return unicodedata.normalize('NFKD', input).encode('ASCII', 'ignore').decode()


class QuickSwitcherItem(urwid.AttrMap):
    def __init__(self, icon, title, id):
        markup = [' ', icon, ' ', title]
        self.id = id
        super(QuickSwitcherItem, self).__init__(
            urwid.SelectableIcon(markup),
            None,
            {
                None: 'active_quick_switcher_item',
                'quick_search_presence_active': 'quick_search_active_focus',
                'quick_search_presence_away': 'active_quick_switcher_item'
            }
        )


class QuickSwitcherList(urwid.ListBox):
    def __init__(self, items):
        self.body = urwid.SimpleFocusListWalker(items)
        super(QuickSwitcherList, self).__init__(self.body)


class QuickSwitcher(urwid.AttrWrap):
    __metaclass__ = urwid.MetaSignals
    signals = ['close_quick_switcher', 'go_to_channel']

    def __init__(self, base, event_loop):
        self.event_loop = event_loop
        self.channels = []
        self.dms = []
        for channel in Store.instance.state.channels:
            if channel.get('is_channel', False):
                self.channels.append({
                    'icon': get_icon('private_channel'),
                    'title': channel['name'],
                    'id': channel['id']
                })
            elif channel.get('is_group', False):
                self.channels.append({
                    'id': channel['id'],
                    'icon': get_icon('channel'),
                    'title': channel['name'],
                })
        for dm in Store.instance.state.dms:
            user = Store.instance.find_user_by_id(dm['user'])
            if user:
                name = user.get('display_name') or user.get('real_name') or user['name']
                online = user['id'] in Store.instance.state.online_users
                if user['id'] == 'USLACKBOT':
                    icon = ('quick_search_presence_active', get_icon('heart'))
                    self.dms.append({'id': dm['id'], 'icon': icon, 'title': name, 'type': 'user', 'members': [name]})
                elif online:
                    icon = ('quick_search_presence_active', get_icon('online'))
                    self.dms.append({'id': dm['id'], 'icon': icon, 'title': name, 'type': 'user', 'members': [name]})
                else:
                    icon = ('quick_search_presence_away', get_icon('offline'))
                    self.dms.append({'id': dm['id'], 'icon': icon, 'title': name, 'type': 'user', 'members': [name]})

        for group in Store.instance.state.groups:
            member_ids = set(group['members'])
            members = [
                Store.instance.find_user_by_id(member_id)
                for member_id in member_ids
            ]
            if all(members):
                member_names = []
                for member in members:
                    name = Store.instance.get_user_display_name(member)
                    if name != 'Pascal Bugnion':
                        member_names.append(name)
                title = ", ".join(member_names)
                self.dms.append(
                    {'id': group['id'], 'icon': 'G', 'title': title, 'type': 'group', 'members': member_names}
                )
        self.header = urwid.Edit('')
        self.user_dm_map = self.build_user_dm_lookup(self.dms)
        self.channel_map = self.build_channel_lookup(self.channels)
        widgets = [QuickSwitcherItem(item['icon'], item['title'], item['id']) for item in self.channels + self.dms]
        self.quick_switcher_list = QuickSwitcherList(widgets)
        switcher = urwid.LineBox(
            urwid.Frame(self.quick_switcher_list, header=self.header),
            title='Jump to...',
            title_align='left'
        )
        overlay = urwid.Overlay(
            switcher,
            base,
            align='center',
            width=('relative', 40),
            valign='middle',
            height=15
        )
        self.last_keypress = (time.time() - 0.3, None)
        super(QuickSwitcher, self).__init__(overlay, 'quick_switcher_dialog')


    def build_user_dm_lookup(self, dms):
        user_dm_map = defaultdict(list)
        for dm in self.dms:
            for name in dm['members']:
                user_dm_map[remove_diacritic(name.lower())].append(dm)
        return PartialMatchLookup(user_dm_map)

    def build_channel_lookup(self, channels):
        return PartialMatchLookup({
            remove_diacritic(channel['title'].lower()): channel
            for channel in channels
        })

    @property
    def filtered_items(self):
        return self.original_items

    @filtered_items.setter
    def filtered_items(self, items):
        self.quick_switcher_list.body[:] = [
            QuickSwitcherItem(item['icon'], item['title'], item['id'])
            for item in items
        ]

    def set_filter(self, loop, data):
        text = self.header.get_edit_text()
        if len(text) > 0:
            text = remove_diacritic(text).lower()
            if text[0] == '@':
                filtered_items = self.single_user_search(text[1:])
                self.filtered_items = sorted(filtered_items, key=lambda item: len(item['members']))
            elif "," in text:
                users = text.split(",")
                users = [user.strip() for user in users]
                users = [user for user in users if user]
                filtered_items = self.multiple_user_search(users)
                self.filtered_items = sorted(filtered_items, key=lambda item: len(item['members']))
            elif text[0] == '#':
                filtered_items = self.channel_search(text[1:])
                self.filtered_items = sorted(filtered_items, key=lambda channel: len(channel['title']))
            else:
                filtered_channels = self.channel_search(text)
                filtered_dms = self.single_user_search(text)
                sorted_channels = sorted(filtered_channels, key=lambda channel: len(channel['title']))
                sorted_dms = sorted(filtered_dms, key=lambda dm: len(dm['members']))
                self.filtered_items = sorted_channels + sorted_dms
        else:
            self.filtered_items = self.channels

    def single_user_search(self, user):
        matching_items = itertools.chain.from_iterable(
            self.user_dm_map.get_all(user).values()
        )
        found_ids = set()
        items = []
        for item in matching_items:
            if item['id'] not in found_ids:
                items.append(item)
                found_ids.add(item['id'])
        return items

    def multiple_user_search(self, users):
        [first, *rest] = users
        starting_items = self.single_user_search(first)
        for user in rest:
            remaining_items = []
            for item in starting_items:
                hygiened_members = [
                    remove_diacritic(member.lower()) for member
                    in item['members']
                ]
                if PartialMatchList(hygiened_members).contains(user):
                    remaining_items.append(item)
            starting_items = remaining_items
        return starting_items

    def channel_search(self, channel):
        matching_items = self.channel_map.get_all(channel).values()
        return matching_items


    def keypress(self, size, key):
        reserved_keys = ('up', 'down', 'esc', 'page up', 'page down')
        if key in reserved_keys:
            return super(QuickSwitcher, self).keypress(size, key)
        elif key == 'enter':
            focus = self.quick_switcher_list.body.get_focus()
            if focus[0]:
                urwid.emit_signal(self, 'go_to_channel', focus[0].id)
                return True
        self.header.keypress((size[0],), key)
        now = time.time()
        if now - self.last_keypress[0] < 0.3 and self.last_keypress[1] is not None:
            self.event_loop.remove_alarm(self.last_keypress[1])
        self.last_keypress = (now, self.event_loop.set_alarm_in(0.3, self.set_filter))

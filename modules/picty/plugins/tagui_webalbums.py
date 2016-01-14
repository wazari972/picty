"""

    picty
    Copyright (C) 2013  Damien Moore

License:

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import threading
import cPickle

import os.path
import gobject
import gtk

from picty import pluginbase
from picty import baseobjects
from picty import imagemanip
from picty import backend
from picty import settings
from picty.uitools import dialogs

from webalbums.downloader import tools as wad_tools

import logging

log = logging.getLogger('webalbums.tag')

class TagCloud():

    def __init__(self):
        self.tags = dict()

    def __repr__(self):
        return self.tags.__repr__()

    def copy(self):
        c = TagCloud()
        c.tags = self.tags.copy()
        return c

    def empty(self):
        self.tags = dict()

    def tag_add(self, keywords):
        for kw in keywords:
            if kw in self.tags:
                self.tags[kw] += 1
            else:
                self.tags[kw] = 1

    def tag_remove(self, keywords):
        for kw in keywords:
            if kw not in self.tags:
                log.warning("Removing item {} with keyword {} not in tag cloud".format(item, kw))
                continue
            
            if self.tags[kw] > 1:
                self.tags[kw] -= 1
            else:
                del self.tags[kw]                

    def add(self, item):
        if item.meta is None:
            return False
        
        try:
            self.tag_add(item.meta['Keywords'])
        except:
            return False
        
        return True

    def remove(self, item):
        try:
            if item.meta is None:
                return False
            self.tag_remove(item.meta['Keywords'])
        except:
            return False
        
        return True

    def update(self, item, old_meta):
        try:
            self.tag_remove(old_meta['Keywords'])
        except:
            pass
        
        try:
            self.tag_add(item.meta['Keywords'])
        except:
            pass

    def revert(self, item):
        try:
            self.tag_remove(item.meta['Keywords'])
        except:
            pass
        try:
            self.tag_add(item.meta_backup['Keywords'])
        except:
            pass


# M_TYPE=0 #type of row: 0=Favorite, 1=Other, 2=Category, 3=Tag
# M_KEY=1 #name of the tag or category
# M_PIXBUF=2 #pixbuf image displayed next to tag
# M_DISP=3 #display text
# M_CHECK=4 #state of check box
# M_PIXPATH=5 #path to pixbuf

user_tag_layout_default = [
    ((0, 0), 2, 'loading', '<b>loading ...</b>', None),
]

def import_pdb_set_trace():
    from PyQt5.QtCore import pyqtRemoveInputHook
    pyqtRemoveInputHook()
    import pdb;pdb.set_trace()

class WalkWebAlbumTagTreeJob(backend.WorkerJob):
    
    def __init__(self, worker, collection, browser, tagframe):
        backend.WorkerJob.__init__(self, 'WALKDIRECTORY', 700, worker, collection, browser)
        self.done = False
        self.last_walk_state = None
        self.tag_walker = None
        self.tagframe = tagframe
        self.user_tag_info = []
        self.tree_path_position = [0, -1]
        
    def _walk_taginfo(self, taginfo):
        tag = taginfo.find("tag")
        
        tid = tag.get("id")
        name = tag.find("name").text

        yield tid, name

        children = taginfo.find("children")
        
        if not len(children):
            return

        yield True
        for taginfo in children.findall("tagInfo"):
            for tag in self._walk_taginfo(taginfo):
                yield tag
                
        yield False
    
    def _walk_tagtree(self):
        tagtree = wad_tools.get_a_page("Tags?special=CLOUD", save=False, parse_and_transform=True)

        for taginfo in tagtree.find("tags").find("cloud").findall("tagInfo"):
            for tag in self._walk_taginfo(taginfo):
                yield tag
            
    def __call__(self):
        """ Example of tree_path: [
        [tree_path, type,tag_name,display_text,   icon_path]
        [[0, 0],    2, 'People', '<b>People</b>', '.../People'], 
        [[0, 0, 0], 3, 'toto',   'toto (0)',      '.../toto'],
        [[0, 1],    2, 'Places', '<b>Places</b>', '.../Places'],
        [[0, 2],    2, 'Events', '<b>Events</b>', '.../Events'], 
        [[0, 2, 0], 2, 'cat',    '<b>cat</b>',    '.../cat']
        ]"""

        jobs = self.worker.jobs

        try:
            if not self.tag_walker:
                log.info('Starting WebAlbums tagtree walk on {}'.format(self.collection.name))
                self.tag_walker = self._walk_tagtree()
                self.done = False
                
        except StopIteration:
            self.collection_walker = None
            log.error('Aborted directory walk on {}'.format(self.collection.name))
            return True

        while jobs.ishighestpriority(self) and not self.done:
            backend.idle_add(self.browser.update_backstatus, True, 'Scanning the tag tree')
            
            try:
                tag = self.tag_walker.next()
            except StopIteration:
                self.done = True
                break


            
            if tag is True:     
                self.tree_path_position.append(-1)
                continue
            elif tag is False:
                self.tree_path_position.pop()
                continue
            else:
                uid, name = tag
                
            self.tree_path_position[-1] += 1
            tree_path = []
            tree_path[:] = self.tree_path_position
                
            TYPE = 2
            ICON_PATH = None
                
            entry = (tree_path, TYPE, name, "<b>{}</b>".format(name), ICON_PATH)
            print("{} {}".format(entry[0], name))
            self.user_tag_info.append(entry)

        if self.done:
            self.tagframe.set_user_tags(self.user_tag_info)
        
            return True
        else:
            return False

class WebAlbumsTagSidebarPlugin(pluginbase.Plugin):
    name = 'WebAlbumsTagSidebar'
    display_name = 'Tags'
    api_version = '0.1.0'
    version = '0.1.0'

    def __init__(self):
        log.info('INITIALIZED TAG SIDEBAR PLUGIN')

    def plugin_init(self, mainframe, app_init):
        self.mainframe = mainframe
        self.worker = mainframe.tm
        self.block_refresh = {}
        user_tag_layout = user_tag_layout_default
        data = settings.load_addon_prefs('tag_plugin_settings')

        # ignore save tag_layout
        #if data:
        #   user_tag_layout = data['tag_layout']
        #

        # use loading layout for now
        self.tagframe = TagFrame(self.mainframe, user_tag_layout_default)
        self.tagframe.show_all()
        
        self.mainframe.sidebar.append_page(self.tagframe, gtk.Label("WebAlbums Tags"))
        
        self.mainframe.connect("tag-row-dropped", self.tag_dropped_in_browser)
        self.mainframe.connect("view-rebuild-complete",
                               self.view_rebuild_complete)

    def plugin_shutdown(self, app_shutdown=False):
        data = {
            'version': self.version,
            'tag_layout': self.tagframe.get_user_tags()
        }
        settings.save_addon_prefs('tag_plugin_settings', data)
        legacy_file = os.path.join(settings.data_dir, 'tag-layout')

    def t_collection_item_added(self, collection, item):
        """item was added to the collection"""
        log.error("add {} to {}".format(item, collection))
        return
    
        self.tagframe.tag_cloud[collection].add(item)
        self.thread_refresh()

    def t_collection_item_removed(self, collection, item):
        """item was removed from the collection"""
        log.error("remove {} from {}".format(item, collection))
        return
    
        self.tagframe.tag_cloud[collection].remove(item)
        self.thread_refresh()

    def t_collection_item_metadata_changed(self, collection, item, meta_before):
        """item metadata has changed"""
        log.error("changed metadata {} from {}".format(item, collection))
        return
    
        if collection != None:
            self.tagframe.tag_cloud[collection].update(item, meta_before)
            i = collection.get_active_view().find_item(item)
            if i >= 0:
                self.tagframe.tag_cloud_view[
                    collection.get_active_view()].update(item, meta_before)
            self.thread_refresh()

    def t_collection_item_added_to_view(self, collection, view, item):
        """item in collection was added to view"""
        log.error("item added to view {} from  {}".format(item, collection))
        return
    
        self.tagframe.tag_cloud_view[view].add(item)
        self.thread_refresh()

    def t_collection_item_removed_from_view(self, collection, view, item):
        """item in collection was removed from view"""
        log.error("item remove from view {} from  {}".format(item, collection))
        return
        self.tagframe.tag_cloud_view[view].remove(item)
        self.thread_refresh()

    def t_collection_modify_start_hint(self, collection):
        log.error("modify start hind from  {}".format(collection))
        return
    
        self.block_refresh[collection] = True

    def t_collection_modify_complete_hint(self, collection):
        log.error("modify complete hind from  {}".format(collection))
        return
    
        del self.block_refresh[collection]
        self.thread_refresh()

    def thread_refresh(self):
        if self.worker.active_collection not in (self.block_refresh):
            gobject.idle_add(self.tagframe.start_refresh_timer)

    def tag_dropped_in_browser(self, mainframe, browser, item, tag_widget, path):
        log.critical("tag {} dropped from item {} from {}".format(path, item, collection))
        return
        
        tags = self.tagframe.get_tags(path)
        if not item.selected:
            imagemanip.toggle_tags(item, tags)
        else:
            self.worker.keyword_edit(tags, True)

    def t_collection_loaded(self, collection):
        """collection has loaded into main frame"""
        log.critical("collection {} loaded".format(collection))
        
        job = WalkWebAlbumTagTreeJob(self.worker, collection, self.mainframe.active_browser(), self.tagframe)
        self.worker.queue_job_instance(job)

        return
        
        self.tagframe.tag_cloud[collection] = TagCloud()
        view = collection.get_active_view()
        if view:
            self.tagframe.tag_cloud_view[view] = TagCloud()
        for item in collection:
            self.tagframe.tag_cloud[collection].add(item)
            
        self.thread_refresh()

    def t_collection_closed(self, collection):
        log.critical("collection {} closed".format(collection))
        
        del self.tagframe.tag_cloud[collection]
        try:
            del self.tagframe.tag_cloud_view[collection.get_active_view()]
        except KeyError:
            pass
        self.thread_refresh()

    def collection_activated(self, collection):
        log.critical("collection {} activated".format(collection))
        self.tagframe.refresh()

    def t_view_emptied(self, collection, view):
        """the view has been flushed"""
        log.critical("collection {} emptied".format(collection))
        
        self.tagframe.tag_cloud_view[view] = TagCloud()
        self.tagframe.refresh()

    def t_view_updated(self, collection, view):
        """the view has been updated"""
        log.critical("view updated from {}".format(collection))
        
        self.tagframe.tag_cloud_view[view] = TagCloud()
        for item in view:
            self.tagframe.tag_cloud_view[view].add(item)
        self.tagframe.refresh()

    def view_rebuild_complete(self, mainframe, browser):
        log.critical("view rebuild complete from {}".format(browser))
        self.tagframe.refresh()

    def load_user_tags(self, filename):
        log.error("load user tags from {}".format(filename))
        
        pass

    def save_user_tags(self, filename):
        log.error("save user tags from {}".format(filename))
        pass

##


# TODOs: Moving rows should move children


# provides gui elements for working with tags
# 1. tree interface for choosing tags to "paint" onto  images
# 2. tag selector dialog
# 3. tag auto-completer
# tag collection object (keeps track of available tags and counts)


class TagFrame(gtk.VBox):
    # column indices of the treestore
    M_TYPE = 0  # type of row: 0=Favorite, 1=Other, 2=Category, 3=Tag
    M_KEY = 1  # name of the tag or category
    M_PIXBUF = 2  # pixbuf image displayed next to tag
    M_DISP = 3  # display text
    M_CHECK = 4  # state of check box
    M_PIXPATH = 5  # path to pixbuf

    def __init__(self, mainframe, user_tag_info):
        gtk.VBox.__init__(self)
        self.set_spacing(5)
        self.user_tags = {}
        # these are updated on the worker thread, be careful about accessing on
        # the main thread (should use locks)
        self.tag_cloud = {}
        self.tag_cloud_view = {}
        self.mainframe = mainframe
        self.worker = mainframe.tm
        label = gtk.Label()
        label.set_markup("<b>Tags</b>")
        label.set_alignment(0.05, 0)

        self.model = gtk.TreeStore(int, str, gtk.gdk.Pixbuf, str, 'gboolean', str)
        
        self.tv = gtk.TreeView(self.model)

        self.tv.set_headers_visible(False)
        self.tv.connect("row-activated", self.tag_activate)
        
        tvc = gtk.TreeViewColumn()
        txt = gtk.CellRendererText()
        pb = gtk.CellRendererPixbuf()
        tvc.pack_start(pb, False)
        tvc.pack_start(txt, True)
        tvc.add_attribute(pb, 'pixbuf', self.M_PIXBUF)
        tvc.add_attribute(txt, 'markup', self.M_DISP)
        
        toggle = gtk.CellRendererToggle()
        toggle.set_property("activatable", True)
        toggle.connect("toggled", self.toggle_signal)
        tvc_check = gtk.TreeViewColumn(None, toggle, active=self.M_CHECK)

        self.tv.append_column(tvc)
        self.tv.enable_model_drag_dest([('tag-tree-row', gtk.TARGET_SAME_WIDGET, 0),
                                        ('image-filename', gtk.TARGET_SAME_APP, 1)],
                                       gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_MOVE)
        self.tv.connect("drag-data-received", self.drag_receive_signal)
        self.tv.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                                         [('tag-tree-row', gtk.TARGET_SAME_APP, 0)],
                                         gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE)
        self.tv.connect("drag-data-get", self.drag_get_signal)
        self.tv.add_events(gtk.gdk.BUTTON_MOTION_MASK)
        self.tv.connect("button-release-event", self.context_menu)

        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.add(self.tv)
        scrolled_window.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        self.pack_start(scrolled_window)

        button_box = gtk.HButtonBox()
        button_box.show_all()
        self.pack_start(button_box, False)

        self.model.append(None, (0, 'favorites', None, '<b>Categorized</b>', False, ''))
        self.model.append(None, (1, 'other', None, '<b>Uncategorized</b>', False, ''))
        self.set_user_tags(user_tag_info)
        self.timer = None

    def start_refresh_timer(self):
        if self.timer != None:
            self.timer.cancel()
        self.timer = threading.Timer(1, self.refresh)
        self.timer.start()

    def context_menu(self, widget, event):
        if event.button == 3:
            row_path, tvc, tvc_x, tvc_y = self.tv.get_path_at_pos(int(event.x), int(event.y))
            row_iter = self.model.get_iter(row_path)
            menu = gtk.Menu()

            def menu_add(menu, text, callback):
                item = gtk.MenuItem(text)
                item.connect("activate", callback, row_iter)
                menu.append(item)
                item.show()
                
            if row_path[0] == 0:
                if self.model[row_path][self.M_TYPE] in (0, 2):
                    menu_add(menu, "New _Category", self.add_category)
                    menu_add(menu, "New _Tag", self.add_tag)
                    
                if len(row_path) > 1:
                    if self.model[row_path][self.M_TYPE] == 3:
                        menu_add(menu, "_Delete Tag", self.remove_tag)
                        menu_add(menu, "Re_name Tag", self.rename_tag)
                        menu_add(menu, "_Apply to Selected Images",
                                 self.apply_tag_to_browser_selection)
                        menu_add(menu, "Remov_e from Selected Images",
                                 self.remove_tag_from_browser_selection)
                        menu_add(menu, "Show _Matches in Current View",
                                 self.tag_activate_view)
                        
                    if self.model[row_path][self.M_TYPE] == 2:
                        menu_add(menu, "_Sort Category", self.sort_category)
                        menu_add(menu, "_Delete Category",
                                 self.remove_category)
                        menu_add(menu, "Re_name Category",
                                 self.rename_category)
                        
                    if self.model[row_path][self.M_PIXBUF] != None:
                        menu_add(menu, "Remove _Icon", self.remove_bitmap)
                else:
                    menu_add(menu, "_Sort", self.sort_category)
                    
            if row_path[0] == 1:
                if len(row_path) > 1:
                    if self.model[row_path][self.M_TYPE] == 3:
                        # todo: for uncategorized tags, the prompt is redundant
                        menu_add(menu, "_Delete Tag", self.remove_tag)
                        menu_add(menu, "Re_name Tag", self.rename_tag)
                        menu_add(menu, "Show _Matches in Current View",
                                 self.tag_activate_view)
            if len(menu.get_children()) > 0:
                menu.popup(parent_menu_shell=None, parent_menu_item=None,
                           func=None, button=1, activate_time=0, data=0)

    def remove_bitmap(self, widget, iter):
        self.delete_user_bitmap(iter)

    def add_tag(self, widget, parent):
        from picty.uitools import completions
        
        kw = self.mainframe.entry_dialog( 'Add a Tag', 'Name:', completions.TagCompletion)
        if not kw:
            return
        try:
            new_iter = self.model.append(parent, (3, kw, None, kw + ' (%i)' % (0,), False, ''))
            new_path = self.model.get_path(new_iter)
            self.user_tags[k] = gtk.TreeRowReference(self.model, new_path)
        except:
            pass

    def remove_tag(self, widget, iter):
        kw = self.model[iter][self.M_KEY]
        rename_response = dialogs.prompt_dialog(
            "Delete Tag", "Would you like to remove the tag '{}' from all images in your collection?".format(kw))
        
        if rename_response == 2:
            return
        
        self.model.remove(iter)
        if kw in self.user_tags:
            del self.user_tags[k]
            
        if rename_response == 0:
            # todo: if this job is busy the request will fail so probably
            # shouldn't actually rename the tag unless the request succeeds
            self.worker.keyword_edit('"{}"'.format(kw), False, True, False, backend.EDIT_COLLECTION)

    def rename_tag(self, widget, iter):
        from picty.uitools import completions
        
        old_key = self.model[iter][self.M_KEY]
        kw = self.mainframe.entry_dialog('Rename Tag', 'New Name:', completions.TagCompletion, old_key)
        
        if not kw or kw == old_key:
            return
        
        rename_response = dialogs.prompt_dialog("Rename Tag", 'Would you like to replace the tag "{}" with "{}" for all images in your collection'.format(old_key, kw))
        
        if rename_response == 2:
            return
        
        self.model[iter][self.M_KEY] = kw
        self.model[iter][self.M_DISP] = kw.replace('&', '&amp;')
        
        try:
            self.user_tags[kw] = self.user_tags[old_key]
            del self.user_tags[old_key]
        except:
            pass
        
        if rename_response == 0:
            # todo: if this job is busy the request will fail so probably
            # shouldn't actually rename the tag unless the request succeeds
            self.worker.keyword_edit('"{}" "{}"'.format(old_key, kw), False, False, True, backend.EDIT_COLLECTION)

    def add_category(self, widget, parent):
        kw = self.mainframe.entry_dialog('Add a Category', 'Name:')
        if not kw:
            return
        try:
            self.model.append(parent, (2, kw, None, '<b>{}</b>'.format(kw), False, ''))
        except:
            pass

    def remove_category(self, widget, iter):
        try:
            self.model.remove(iter)
        except:
            pass

    def rename_category(self, widget, iter):
        old_key = self.model[iter][self.M_KEY]
        kw = self.mainframe.entry_dialog('Rename Category', 'New Name:', default=old_key)
        
        if not kw or kw == old_key:
            return
        
        try:
            self.model[iter][self.M_KEY] = kw
            self.model[iter][self.M_DISP] = '<b>{}</b>'.format(k.replace('&', '&amp;'))
        except:
            pass

    def apply_tag_to_browser_selection(self, widget, iter):
        row = self.model[iter]
        if row[self.M_TYPE] != 3:
            return
        
        keyword_string = '"{}"'.format(row[self.M_KEY])
        
        if keyword_string:
            self.worker.keyword_edit(keyword_string)

    def remove_tag_from_browser_selection(self, widget, iter):
        row = self.model[iter]
        
        if row[self.M_TYPE] != 3:
            return
        
        keyword_string = '"{}"'.format(row[self.M_KEY])
        
        if keyword_string:
            self.worker.keyword_edit(keyword_string, True)

    def tag_mode_toggle_signal(self, button):
        self.mainframe.active_browser().imarea.grab_focus()

    def iter_all_children(self, iter_node):
        """iterate all rows from iter_node and their children"""
        
        while iter_node:
            yield self.model[iter_node]
            
            for r in self.iter_all_children(self.model.iter_children(iter_node)):
                yield r
                
            iter_node = self.model.iter_next(iter_node)

    def iter_row_children(self, iter_node):
        """generator for current row and all children"""
        
        yield self.model[iter_node]
        
        for x in self.iter_all_children(self.model.iter_children(iter_node)):
            yield x

    def iter_children(self, iter):
        iter = self.model.iter_children(iter)
        
        while iter:
            yield self.model[iter]
            iter = self.model.iter_next(iter)

    def iter_all(self):
        """iterate over entire tree"""
        
        for x in self.iter_all_children(self.model.get_iter_root()):
            yield x

    def move_row_and_children(self, iter_node, dest_iter, rownum=None):
        def copy(iter_node, dest_iter, rownum=None):
            row = list(self.model[iter_node])
            
            if rownum != None:
                dest_iter = self.model.insert(dest_iter, rownum, row)
            else:
                n = self.model.iter_n_children(dest_iter)
                
                for i in range(n):
                    it = self.model.iter_nth_child(dest_iter, i)
                    if self.model[it][self.M_DISP].lower() > row[self.M_DISP].lower():
                        dest_iter = self.model.insert(dest_iter, i, row)
                        n = -1
                        break
                    
                if n >= 0:
                    dest_iter = self.model.append(dest_iter, row)
                    
            row = self.model[dest_iter]
            if row[self.M_TYPE] == 3:
                self.user_tags[row[self.M_KEY]] = gtk.TreeRowReference(self.model, self.model.get_path(dest_iter))
                
            iter_node = self.model.iter_children(iter_node)
            while iter_node:
                copy(iter_node, dest_iter)
                iter_node = self.model.iter_next(iter_node)
                
        iter = dest_iter
        while iter:  # abort if user is trying to drag a row to one of its children
            if self.model.get_path(iter) == self.model.get_path(iter_node):
                return
            iter = self.model.iter_parent(iter)
            
        copy(iter_node, dest_iter, rownum)
        self.model.remove(iter_node)

    def sort_category(self, widget, iter):
        """menu callback to sort alphabetically by tag name the child rows of iter"""
        # implements a crude bubble search (if I remember my algorithms correctly)
        i = 0
        names = []
        basepath = self.model.get_path(iter)
        it = self.model.iter_children(iter)
        while it:
            path = self.model.get_path(it)
            itn = self.model.iter_next(it)
            if itn:
                pathn = self.model.get_path(itn)
                if self.model[path][self.M_DISP].lower() > self.model[pathn][self.M_DISP].lower():
                    self.model.swap(it, itn)
                    i -= 1
                else:
                    i += 1
                if i <= 0:
                    i = 0
                iter = self.model.get_iter(basepath)
                if i < self.model.iter_n_children(iter) - 1:
                    it = self.model.iter_nth_child(iter, i)
                else:
                    break
            else:
                break

    def get_checked_tags(self):
        return [it[self.M_KEY] for it in self.iter_all() if it[self.M_TYPE] == 3 and it[self.M_CHECK]]

    def get_tags(self, path):
        iter = self.model.get_iter(path)
        return [it[self.M_KEY] for it in self.iter_row_children(iter) if it[self.M_TYPE] == 3]

    def drag_receive_signal(self, widget, drag_context, x, y, selection_data, info, timestamp):
        """something was dropped on a tree row"""
        
        drop_info = self.tv.get_dest_row_at_pos(x, y)
        if drop_info:
            drop_row, pos = drop_info
            drop_iter = self.model.get_iter(drop_row)
            data = selection_data.data
            
            if selection_data.type == 'tag-tree-row':
                paths = data.split('-')
                iters = []
                for path in paths:
                    iters.append(self.model.get_iter(path))
                for it in iters:
                    path = list(self.model.get_path(drop_iter))
                    rownum = path.pop()
                    if self.model[it] < 2:
                        continue
                    
                    if self.model[drop_iter][self.M_TYPE] == 3:
                        if pos in [gtk.TREE_VIEW_DROP_AFTER, gtk.TREE_VIEW_DROP_INTO_OR_AFTER]:
                            rownum += 1
                        drop_iter = self.model.iter_parent(drop_iter)
                        self.move_row_and_children(it, drop_iter, rownum)
                        
                    else:
                        if pos in [gtk.TREE_VIEW_DROP_INTO_OR_BEFORE, gtk.TREE_VIEW_DROP_INTO_OR_AFTER]:
                            self.move_row_and_children(it, drop_iter)
                        else:
                            if pos == gtk.TREE_VIEW_DROP_AFTER:
                                pos += 1
                            self.move_row_and_children(it, drop_iter, pos)
                
            elif selection_data.type == 'image-filename':
                model_path = list(self.model.get_path(drop_iter))
                if len(model_path) <= 1 or model_path[0] == 1:
                    return
                
                path = data
                from picty import baseobjects
                item = baseobjects.Item(path)
                ind = self.worker.active_collection.find(item)
                if ind < 0:
                    return False
                
                thumb_pb = self.worker.active_collection(ind).thumb
                if thumb_pb:
                    width, height = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)
                    width = width * 3 / 2
                    height = height * 3 / 2
                    tw = thumb_pb.get_width()
                    th = thumb_pb.get_height()
                    if width / height > tw / th:
                        height = width * th / tw
                    else:
                        width = height * tw / th
                    thumb_pb = thumb_pb.scale_simple(
                        width * 3 / 2, height * 3 / 2, gtk.gdk.INTERP_BILINEAR)
                    self.set_and_save_user_bitmap(drop_iter, thumb_pb)
                # get the thumbnail and set the drop_iter row pixbuf and pixpath accordingly
                pass

    def drag_get_signal(self, widget, drag_context, selection_data, info, timestamp):
        treeselection = self.tv.get_selection()
        model, paths = treeselection.get_selected_rows()
        strings = []
        
        for path in paths:
            log.info('drag get {} -> {}'.format(path, self.model[p][self.M_TYPE]))
            
            if self.model[path][self.M_TYPE] in (0, 1):
                continue
            
            strings.append(self.model.get_string_from_iter(self.model.get_iter(path)))
                
        if len(strings) == 0:
            return False
        
        selection_data.set('tag-tree-row', 8, '-'.join(strings))

    def set_user_tags(self, usertaginfo):
        """
        sets the user defined tags
        usertaginfo is a list with each element a sublist containing:
            [tree_path,type,tag_name,display_text,icon_path]
            NB: model contains [tag_name,pixbuf,display_text,check_state,icon_path]
        """
        self.user_tags = {}
        path = self.model.get_iter((0,))
        self.model.remove(path)
        self.model.insert(None, 0, (0, 'favorites', None, '<b>Categorized</b>', False, ''))

        for row in usertaginfo:
            path = tuple(row[0])
            parent = self.model.get_iter(path[0:len(path) - 1])
            self.model.append(parent, [row[1], row[2], None, row[3], False, row[4]])
            self.user_tags[row[2]] = gtk.TreeRowReference(self.model, path)

        self.load_user_bitmaps(usertaginfo)

    def get_user_tags_rec(self, usertaginfo, iter):
        """from a given node iter, recursively appends rows to usertaginfo"""
        while iter:
            row = list(self.model[iter])
            # todo: reverse order of pop is critical here
            row.pop(self.M_CHECK)
            row.pop(self.M_PIXBUF)
            usertaginfo.append([self.model.get_path(iter)] + row)
            self.get_user_tags_rec(usertaginfo, self.model.iter_children(iter))
            iter = self.model.iter_next(iter)

    def get_user_tags(self):
        iter = self.model.get_iter((0,))
        usertaginfo = []
        self.get_user_tags_rec(usertaginfo, self.model.iter_children(iter))
        return usertaginfo

    def load_user_bitmaps(self, usertaginfo):
        for tag in self.user_tags:
            if not tag:
                continue
            
            row = self.model[self.user_tags[tag].get_path()]
            if row[self.M_PIXPATH]:
                try:
                    row[self.M_PIXBUF] = gtk.gdk.pixbuf_new_from_file(row[self.M_PIXPATH])
                except:
                    pass
                
    def delete_user_bitmap(self, tree_path):
        import os
        import os.path
        
        self.model[tree_path][self.M_PIXBUF] = None
        png_path = os.path.join(settings.data_dir, 'tag-png')
        fullname = os.path.join(png_path, self.model[tree_path][self.M_KEY])
        
        try:
            os.remove(fullname)
        except:
            pass

    def set_and_save_user_bitmap(self, tree_path, pixbuf):
        import os.path
        
        if not self.model[tree_path][self.M_KEY]:
            return False
        
        self.model[tree_path][self.M_PIXBUF] = pixbuf
        png_path = os.path.join(settings.data_dir, 'tag-png')
        
        if not os.path.exists(png_path):
            os.makedirs(png_path)
            
        if not os.path.isdir(png_path):
            return False
        
        fullname = os.path.join(png_path, self.model[tree_path][self.M_KEY])
        self.model[tree_path][self.M_PIXPATH] = fullname
        
        try:
            pixbuf.save(fullname, 'png')
        except:
            # todo: log an error or warn user
            pass

    def tag_activate_view(self, widget, iter):
        text = ''
        for row in self.iter_row_children(iter):
            if row[self.M_TYPE] == 3:
                text += 'tag="{}" '.format(row[self.M_KEY])
        if text:
            self.mainframe.filter_entry.set_text('lastview&' + text.strip())
            self.mainframe.filter_entry.activate()

    def tag_activate(self, treeview, path, view_column):
        text = ''
        for row in self.iter_row_children(self.model.get_iter(path)):
            if row[self.M_TYPE] == 3:
                text += 'tag="{}" '.format(row[self.M_KEY])
                
        if text:
            self.mainframe.filter_entry.set_text(text.strip())
            self.mainframe.filter_entry.activate()

    def check_row(self, path, state):
        self.model[path][self.M_CHECK] = state
        
        iter = self.model.get_iter(path)
        for row in self.iter_row_children(iter):
            row[self.M_CHECK] = state
            
        iter = self.model.iter_parent(iter)
        while iter:
            self.model[iter][self.M_CHECK] = reduce(bool.__and__, [r[self.M_CHECK] for r in self.iter_children(iter)], True)
            iter = self.model.iter_parent(iter)

    def toggle_signal(self, toggle_widget, path):
        state = not toggle_widget.get_active()
        self.check_row(path, state)

    def refresh(self):
        collection = self.worker.active_collection
        
        view = (None if collection == None else
                collection.get_active_view())
        
        try:
            # todo: should be using a lock here
            tag_cloud = self.tag_cloud[collection].copy()
        except KeyError:
            tag_cloud = TagCloud()
            
        try:
            tag_cloud_view = self.tag_cloud_view[view].copy()
        except KeyError:
            tag_cloud_view = TagCloud()
            
        path = self.model.get_iter((1,))
        
        self.model.remove(path)
        self.model.append(None, (1, 'other', None, '<b>Uncategorized</b>', False, ''))
        for k in self.user_tags:
            path = self.user_tags[k].get_path()
            row = self.model[path]
            if row[self.M_TYPE] != 3:
                continue
            try:
                row[self.M_DISP] = k.replace('&', '&amp;') + ' (0)'
            except:
                pass
                
        tag_cloud_list = [(t.lower(), t) for t in tag_cloud.tags]
        try:
            tag_cloud_list.sort()
        except UnicodeDecodeError:
            def decode(s):
                try:
                    s.decode('utf8').lower()
                except:
                    log.warning('Bad decode of tag {}'.format(s))
                    return ''
                
            tag_cloud_list = [(decode(t), t) for t in tag_cloud.tags]
            try:
                tag_cloud_list.sort()
            except:
                log.warning('Error sorting tags {}'.format(tag_cloud_list))

        tag_cloud_list = [t[1] for t in tag_cloud_list]
        for k in tag_cloud_list:
            if k in self.user_tags:
                path = self.user_tags[k].get_path()
                if path:
                    try:
                        self.model[path][self.M_DISP] = k.replace('&', '&amp;') + ' (%i/%i)' % (tag_cloud_view.tags[k], tag_cloud.tags[k])
                    except:
                        self.model[path][self.M_DISP] = k.replace('&', '&amp;') + ' (0/%i)' % (tag_cloud.tags[k],)
            else:
                path = self.model.get_iter((1,))
                try:
                    self.model.append(path, (3, k, None, k.replace('&', '&amp;') + ' (%i/%i)' % (tag_cloud_view.tags[k], tag_cloud.tags[k],), False, ''))
                except:
                    self.model.append(path, (3, k, None, k.replace('&', '&amp;') + ' (0/%i)' % (tag_cloud.tags[k],), False, ''))
        self.tv.expand_row((0,), False)
        self.tv.expand_row((1,), False)

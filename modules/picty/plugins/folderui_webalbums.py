'''

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
'''

import threading
import cPickle
import copy

import os.path
import gobject
import gtk

from picty import pluginbase
from picty import baseobjects
from picty import imagemanip
from picty import backend
from picty import settings
from picty.uitools import dialogs


class FolderTreeRebuildJob(backend.WorkerJob):

    def __init__(self, worker, collection, browser, folderframe):
        backend.WorkerJob.__init__(self, 'FOLDERCLOUDREBUILD')
        self.folderframe = folderframe

    def __call__(self):
        if not self.folderframe:
            return True
        
        self.folderframe.folder_cloud.empty()
        for item in self.collection:
            self.folderframe.folder_cloud.add(item)
            
        self.folderframe.folder_cloud_view.empty()
        for item in self.view:
            self.folderframe.folder_cloud_view.add(item)
            
        if self.folderframe:
            gobject.idle_add(self.folderframe.start_refresh_timer)
            
        return True


class FolderTree():
    '''
    python representation of the folder tree of the images in a view or collection in the `folders` attribute
    example folder structure
    /home/user/Pictures
    +a/b.jpg
    +b/c.jpg
    +b/d/e.jpg
    will have `folders` attribute
    [{'a':[{},1],'b':[{'c':[{},1]},2]},3]
    '''

    def __init__(self):
        self.folders = [dict(), 0]

    def __repr__(self):
        return self.folders.__repr__()

    def copy(self):
        c = FolderTree()
        c.folders = copy.deepcopy(self.folders)
        return c

    def empty(self):
        self.folders = dict()

    def folder_add(self, path):
        base = self.folders
        base[1] += 1
        if path == '':
            return
        path_folders = path.split('/')
        for f in path_folders:
            if f in base[0]:
                base[0][f][1] += 1
            else:
                base[0][f] = [dict(), 1]
            base = base[0][f]

    def folder_remove(self, path):
        base = self.folders
        base[1] -= 1
        if path == '':
            return
        path_folders = path.split('/')
        for f in path_folders:
            if f in base[0]:
                if base[0][f][1] > 1:
                    base[0][f][1] -= 1
                else:
                    del base[0][f]
                    return
            else:
                print 'warning: removing item', item, 'with keyword', k, 'not in folder cloud'
                return
            base = base[0][f]

    def add(self, item):
        if item.meta == None:
            return False
        try:
            self.folder_add(os.path.split(item.uid)[0])
        except:
            return False
        return True

    def remove(self, item):
        try:
            if item.meta == None:
                return False
            self.folder_remove(os.path.split(item.uid)[0])
        except:
            return False
        return True

    def update(self, item, old_meta):
        try:
            self.folder_remove(os.path.split(item.uid)[0])
        except:
            pass
        try:
            self.folder_add(os.path.split(item.uid)[0])
        except:
            pass

    def revert(self, item):
        try:
            self.folder_remove(os.path.split(item.uid)[0])
        except:
            pass
        try:
            self.folder_add(os.path.split(item.uid)[0])
        except:
            pass


# M_TYPE=0 #type of row: 0=Favorite, 1=Other, 2=Category, 3=Folder
# M_KEY=1 #name of the folder or category
# M_PIXBUF=2 #pixbuf image displayed next to folder
# M_DISP=3 #display text
# M_CHECK=4 #state of check box
# M_PIXPATH=5 #path to pixbuf


class FolderSidebarPlugin(pluginbase.Plugin):
    name = 'WebAlbumsFolderSidebar'
    display_name = 'Albums'
    api_version = '0.1.0'
    version = '0.1.0'

    def __init__(self):
        print 'INITIALIZED FOLDER SIDEBAR PLUGIN'

    def plugin_init(self, mainframe, app_init):
        self.mainframe = mainframe
        self.worker = mainframe.tm
        self.block_refresh = {}
        data = settings.load_addon_prefs('folder_plugins_settings')
        
        self.folderframe = FolderFrame(self.mainframe, {})
        self.folderframe.show_all()
        self.mainframe.sidebar.append_page(self.folderframe, gtk.Label("Folders"))
        self.mainframe.connect("view-rebuild-complete",
                               self.view_rebuild_complete)

    def plugin_shutdown(self, app_shutdown=False):
        data = {
            'version': self.version,
        }
        settings.save_addon_prefs('folder_plugin_settings', data)

    def t_collection_item_added(self, collection, item):
        """item was added to the collection"""
        if collection is None or not collection.local_filesystem:
            return
        self.folderframe.folder_cloud[collection].add(item)
        self.thread_refresh()

    def t_collection_item_removed(self, collection, item):
        """item was removed from the collection"""
        if collection is None or not collection.local_filesystem:
            return
        self.folderframe.folder_cloud[collection].remove(item)
        self.thread_refresh()

    def t_collection_item_metadata_changed(self, collection, item, meta_before):
        """item metadata has changed"""
        if collection != None:
            if not collection.local_filesystem:
                return
            self.folderframe.folder_cloud[collection].update(item, meta_before)
            i = collection.get_active_view().find_item(item)
            if i >= 0:
                self.folderframe.folder_cloud_view[
                    collection.get_active_view()].update(item, meta_before)
            self.thread_refresh()

    def t_collection_item_added_to_view(self, collection, view, item):
        """item in collection was added to view"""
        if collection is None or not collection.local_filesystem:
            return
        self.folderframe.folder_cloud_view[view].add(item)
        self.thread_refresh()

    def t_collection_item_removed_from_view(self, collection, view, item):
        """item in collection was removed from view"""
        if collection is None or not collection.local_filesystem:
            return
        self.folderframe.folder_cloud_view[view].remove(item)
        self.thread_refresh()

    def t_collection_modify_start_hint(self, collection):
        if collection is None or not collection.local_filesystem:
            return
        self.block_refresh[collection] = True

    def t_collection_modify_complete_hint(self, collection):
        if collection is None or not collection.local_filesystem:
            return
        del self.block_refresh[collection]
        self.thread_refresh()

    def thread_refresh(self):
        if self.worker.active_collection not in (self.block_refresh):
            gobject.idle_add(self.folderframe.start_refresh_timer)

    def folder_dropped_in_browser(self, mainframe, browser, item, folder_widget, path):
        return  # nothing really to do here? Should remove drag to browser
#        print 'folder Plugin: dropped',folder_widget,path
#        folders=self.folderframe.get_folders(path)
#        if not item.selected:
#            imagemanip.toggle_folders(item,folders)
#        else:
#            self.worker.keyword_edit(folders,True)

    def t_collection_loaded(self, collection):
        """collection has loaded into main frame"""
        if not collection.local_filesystem:
            return
        
        self.folderframe.folder_cloud[collection] = FolderTree()
        view = collection.get_active_view()
        if view:
            self.folderframe.folder_cloud_view[view] = FolderTree()
        for item in collection:
            self.folderframe.folder_cloud[collection].add(item)
        self.thread_refresh()

    def t_collection_closed(self, collection):
        if not collection.local_filesystem:
            return
        del self.folderframe.folder_cloud[collection]
        try:
            del self.folderframe.folder_cloud_view[
                collection.get_active_view()]
        except KeyError:
            pass
        self.thread_refresh()

    def collection_activated(self, collection):
        self.folderframe.refresh()

    def t_view_emptied(self, collection, view):
        """the view has been flushed"""
        self.folderframe.folder_cloud_view[view] = FolderTree()
        self.folderframe.refresh()

    def t_view_updated(self, collection, view):
        """the view has been updated"""
        self.folderframe.folder_cloud_view[view] = FolderTree()
        for item in view:
            self.folderframe.folder_cloud_view[view].add(item)
        self.folderframe.refresh()

    def view_rebuild_complete(self, mainframe, browser):
        self.folderframe.refresh()

    def load_user_folders(self, filename):
        pass

    def save_user_folders(self, filename):
        pass


# class FolderModel(gtk.TreeStore):
#    def __init__(self,*args):
#        gtk.TreeStore.__init__(self,*args)
#    def row_draggable(self, path):
#        print 'folder model'
#        return self[path][0]!=''
#    def drag_data_delete(self, path):
#        return False
#    def drag_data_get(self, path, selection_data):
#        return False

class FolderFrame(gtk.VBox):
    """
    provides a tree view for seeing the folder structure of the collection
    and offers double click, and right click menu options to filter the collection to those folders
    TODO: Add support for drag and drop to move files
    """
    # column indices of the treestore
    M_KEY = 0  # name of the folder
    M_DISP = 1  # display text
    M_PIXBUFID = 2  # path to pixbuf

    def __init__(self, mainframe, user_folder_info):
        gtk.VBox.__init__(self)
        self.set_spacing(5)
        # these are updated on the worker thread, be careful about accessing on
        # the main thread (should use locks)
        self.folder_cloud = {}
        self.folder_cloud_view = {}
        self.mainframe = mainframe
        self.worker = mainframe.tm
        label = gtk.Label()
        label.set_markup("<b>Folders</b>")
        label.set_alignment(0.05, 0)
        self.model = gtk.TreeStore(str, str, str)
        self.tv = gtk.TreeView(self.model)
        self.tv.set_headers_visible(False)
        self.tv.connect("row-activated", self.folder_activate_subfolders)
        tvc = gtk.TreeViewColumn()
        txt = gtk.CellRendererText()
        pb = gtk.CellRendererPixbuf()
        tvc.pack_start(pb, False)
        tvc.pack_start(txt, True)
        tvc.add_attribute(pb, 'stock-id', self.M_PIXBUFID)
        tvc.add_attribute(txt, 'markup', self.M_DISP)
        self.tv.append_column(tvc)

        self.tv.add_events(gtk.gdk.BUTTON_MOTION_MASK)
        self.tv.connect("button-release-event", self.context_menu)

        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.add(self.tv)
        scrolled_window.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        self.pack_start(scrolled_window)

        self.timer = None
        self.collection = None

    def start_refresh_timer(self):
        if self.timer != None:
            self.timer.cancel()
        self.timer = threading.Timer(1, self.refresh)
        self.timer.start()

    def context_menu(self, widget, event):
        if event.button == 3:
            (row_path, tvc, tvc_x, tvc_y) = self.tv.get_path_at_pos(
                int(event.x), int(event.y))
            row_iter = self.model.get_iter(row_path)
            menu = gtk.Menu()

            def menu_add(menu, text, callback):
                item = gtk.MenuItem(text)
                item.connect("activate", callback, row_path)
                menu.append(item)
                item.show()

            menu_add(menu, "Show images in this folder and sub folders",
                     self.folder_activate_subfolders)
            menu_add(menu, "Show images in this folder", self.folder_activate)
            menu_add(menu, "Restrict view to images in this folder",
                     self.folder_activate_view)
            menu_add(menu, "Open in file manager", self.open_with_file_manager)
            menu.popup(parent_menu_shell=None, parent_menu_item=None,
                       func=None, button=1, activate_time=0, data=0)

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
            yield iter  # self.model[iter]
            iter = self.model.iter_next(iter)

    def iter_all(self):
        """iterate over entire tree"""
        for x in self.iter_all_children(self.model.get_iter_root()):
            yield x

    def folder_activate_view(self, treeview, path):
        text = 'folder="%s" ' % self.get_folder_subpath(path)
        self.mainframe.filter_entry.set_text('lastview&' + text.strip())
        self.mainframe.filter_entry.activate()

    def folder_activate(self, treeview, path):
        text = 'folder="%s" ' % self.get_folder_subpath(path)
        self.mainframe.filter_entry.set_text(text.strip())
        self.mainframe.filter_entry.activate()

    def folder_activate_subfolders(self, treeview, path, view_column=None):
        text = 'folder~"%s" ' % self.get_folder_subpath(path)
        self.mainframe.filter_entry.set_text(text.strip())
        self.mainframe.filter_entry.activate()

    def open_with_file_manager(self, treeview, path):
        app_cmd = 'xdg-open %s' % (self.get_folder_uri(path))
        import subprocess
        subprocess.Popen(app_cmd, shell=True)

    def get_folder_subpath(self, path):
        path = list(path)
        folder = []
        while len(path) > 1:
            folder.insert(0, self.model[tuple(path)][self.M_KEY])
            path.pop(-1)
        return '/'.join(folder)

    def get_folder_uri(self, path):
        return os.path.join(self.collection.image_dirs[0], self.get_folder_subpath(path))

    def refresh(self):
        collection = self.worker.active_collection
        if collection == None:
            view = None
        else:
            view = collection.get_active_view()
        try:
            # todo: should be using a lock here
            folder_cloud = self.folder_cloud[collection].copy()
        except KeyError:
            folder_cloud = FolderTree()
        try:
            folder_cloud_view = self.folder_cloud_view[view].copy()
        except KeyError:
            folder_cloud_view = FolderTree()
        if self.collection != collection:
            self.model.clear()
            self.collection = collection
            if collection is not None and collection.local_filesystem:
                self.model.append(None, ('', '', gtk.STOCK_DIRECTORY))
        if collection is None or not collection.local_filesystem:
            return

        self.model[(0,)][self.M_DISP] = '<b>%s</b> (%i)' % (
            collection.image_dirs[0], folder_cloud.folders[1])
        root_folder_list = sorted(
            [(t.lower(), t, folder_cloud.folders[0][t]) for t in folder_cloud.folders[0]])
        root_folder_list = [t[1:] for t in root_folder_list]

        def add_folder(parent_iter, folder_list_object):
            """
            recursively add folder object to tree
            """
            for folder_name, data in folder_list_object:
                it = self.model.append(
                    parent_iter, (folder_name, folder_name + ' (%i)' % (data[1]), gtk.STOCK_DIRECTORY))
                folder_list = sorted([(t.lower(), t, data[0][t])
                                      for t in data[0]])
                folder_list = [t[1:] for t in folder_list]
                add_folder(it, folder_list)

        def update_folder(parent_iter, folder_list_object):
            """
            recursively add folder object to tree
            """
            names = [f[0] for f in folder_list_object]
            for ch in self.iter_children(parent_iter):
                ind = names.index(self.model[ch][self.M_KEY])
                if ind < 0:
                    self.model.remove(ch)
                else:
                    del folder_list_object[ind]
                    del names[ind]
            for folder_name, data in folder_list_object:
                it = self.model.append(
                    parent_iter, (folder_name, folder_name + ' (%i)' % (data[1]), gtk.STOCK_DIRECTORY))
                folder_list = sorted([(t.lower(), t, data[0][t])
                                      for t in data[0]])
                folder_list = [t[1:] for t in folder_list]
                add_folder(it, folder_list)
        it = self.model.get_iter((0,))
        update_folder(it, root_folder_list)
        self.tv.expand_row((0,), False)

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

__version__ = '0.8'


# standard imports
import bisect
from datetime import datetime
import os
import shutil
import os.path
import re
import cPickle
import string
import tempfile
import gtk
import time
import logging
import traceback

LOG_LEVEL = logging.DEBUG
LOGFORMAT = "  %(log_color)s%(levelname)-8s%(reset)s | %(log_color)s%(message)s%(reset)s"
from colorlog import ColoredFormatter
logging.root.setLevel(LOG_LEVEL)
formatter = ColoredFormatter(LOGFORMAT)
stream = logging.StreamHandler()
stream.setLevel(LOG_LEVEL)
stream.setFormatter(formatter)
log = logging.getLogger('webalbums_collect')
log.setLevel(LOG_LEVEL)
log.addHandler(stream)

# picty imports
from picty import pluginmanager
from picty import settings
# todo: this is a workaround in case of no pyinotify (partially for windows)
try:
    from picty.fstools import monitor2 as monitor
except:
    monitor = None
from picty import viewsupport
from picty import baseobjects
from picty import simple_parser as sp
from picty.uitools import dialogs
from picty import imagemanip
from picty import backend
from picty.fstools import io
from picty.uitools import widget_builder as wb
import simpleview

from webalbums.downloader import tools as wad_tools

def import_pdb_set_trace():
    from PyQt5.QtCore import pyqtRemoveInputHook
    pyqtRemoveInputHook()
    import pdb;pdb.set_trace()

def cb(xml, url, name): return False

wad_tools.callback = cb

#if not wad_tools.server_on():
#    log.critical("WebAlbums server seems not to be running...")

exist_actions = ['Skip', 'Rename', 'Overwrite Always', 'Overwrite if Newer']
EXIST_SKIP = 0
EXIST_RENAME = 1
EXIST_OVERWRITE = 2
EXIST_OVERWRITE_NEWER = 3

def update_legacy_item(item, image_dir):
    uid = os.path.relpath(item, image_dir)
    new_item = baseobjects.Item(uid)
    new_item.mtime = item.mtime  # todo: move this to the meta dictionary
    new_item.thumburi = item.thumburi
    # a copy of new_item.meta will be stored as new_item.meta_backup if meta
    # has been changed but not saved
    new_item.meta = item.meta
    return new_item


class NamingTemplate(string.Template):

    def __init__(self, template):
        t = template.replace("<", "${").replace(">", "}")
        string.Template.__init__(self, t)


def get_date(item):
    '''
    returns a datetime object containing the date the image was taken or if not available the mtime
    '''
    result = viewsupport.get_ctime(item)
    if result == datetime(1900, 1, 1):
        return datetime.fromtimestamp(item.mtime)
    else:
        return result


def get_year(item):
    '''
    returns 4 digit year as string
    '''
    return '%04i' % get_date(item).year


def get_month(item):
    '''
    returns 2 digit month as string
    '''
    return '%02i' % get_date(item).month


def get_day(item):
    '''
    returns 2 digit day as string
    '''
    return '%02i' % get_date(item).day


def get_datetime(item):
    '''
    returns a datetime string of the form "YYYYMMDD-HHMMSS"
    '''
    d = get_date(item)
    return '%04i%02i%02i-%02i%02i%02i' % (d.year, d.month, d.day, d.hour, d.minute, d.day)


def get_original_name(item):
    '''
    returns a tuple (path,name) for the transfer destination
    '''
    # this only applies to locally stored files
    return os.path.splitext(os.path.split(item.uid)[1])[0]


class VariableExpansion:

    def __init__(self, item):
        self.item = item
        self.variables = {
            'Year': get_year,
            'Month': get_month,
            'Day': get_day,
            'DateTime': get_datetime,
            'ImageName': get_original_name,
        }

    def __getitem__(self, variable):
        return self.variables[variable](self.item)

# def naming_default(item,dest_dir_base):
#    '''
#    returns a tuple (path,name) for the transfer destination
#    '''
#    return dest_dir_base,os.path.split(item.uid)[1]


def name_item(item, dest_base_dir, naming_scheme):
    subpath = NamingTemplate(naming_scheme).substitute(VariableExpansion(item))
    ext = os.path.splitext(item.uid)[1]
    fullpath = os.path.join(dest_base_dir, subpath + ext)
    return os.path.split(fullpath)

naming_schemes = [
    ("<ImageName>", "<ImageName>", False),
    ("<Year>/<Month>/<ImageName>", "<Year>/<Month>/<ImageName>", True),
    ("<Y>/<M>/<DateTime>-<ImageName>", "<Year>/<Month>/<DateTime>-<ImageName>", True),
    ("<Y>/<M>/<Day>/<ImageName>", "<Year>/<Month>/<Day>/<ImageName>", True),
    ("<Y>/<M>/<Day>/<DateTime>-<ImageName>",
     "<Year>/<Month>/<Day>/<DateTime>-<ImageName>", True),
]


def altname(pathname):
    dirname, fullname = os.path.split(pathname)
    name, ext = os.path.splitext(fullname)
    i = 0
    while os.path.exists(pathname):
        i += 1
        aname = name + '_(%i)' % i
        pathname = os.path.join(dirname, aname + ext)
    return pathname


class LocalTransferOptionsBox(gtk.VBox):

    def __init__(self, collection):
        gtk.VBox.__init__(self)
        self.transfer_frame = gtk.Expander("Advanced Transfer Options")
        self.pack_start(self.transfer_frame)
        self.transfer_box = gtk.VBox()
        self.transfer_frame.add(self.transfer_box)

        # todo:move PathnameEntry to widgetbuilder
        self.base_dir_entry = dialogs.PathnameEntry(
            '', '', "Choose transfer directory")
        self.base_dir_entry.set_path(collection.image_dirs[0])

        self.widgets = wb.LabeledWidgets([
            ('base_dest_dir', 'Destination Path:', self.base_dir_entry),
            ('name_scheme', 'Naming Scheme:', wb.ComboBox(
                [n[0] for n in naming_schemes])),
            ('action_if_exists', 'Action if Destination Exists:',
             wb.ComboBox(exist_actions)),
        ])

        self.widgets['action_if_exists'].set_active(0)
        self.widgets['name_scheme'].set_active(3)
        self.transfer_box.pack_start(self.widgets)

    def get_options(self):
        return {
            'base_dest_dir': self.base_dir_entry.get_path(),
            'name_scheme': self.widgets['name_scheme'].get_form_data(),
            'action_if_exists': self.widgets['action_if_exists'].get_form_data(),
        }

    def set_options(self, values):
        self.base_dir_entry.set_path(values['base_dest_dir'])
        self.widgets['name_scheme'].set_form_data(values['name_scheme'])
        self.widgets['action_if_exists'].set_form_data(
            values['action_if_exists'])


class LocalStorePrefWidget(gtk.VBox):

    def __init__(self, value_dict=None):
        gtk.VBox.__init__(self)
        box, self.name_entry = dialogs.box_add(
            self, [(gtk.Entry(), True, None)], 'Collection Name: ')
        self.path_entry = dialogs.PathnameEntry(
            '', 'Path to Images: ', 'Choose a Directory', directory=True)
        self.pack_start(self.path_entry, False)
        self.name_entry.connect("changed", self.name_changed)
        self.path_entry.path_entry.connect("changed", self.path_changed)

        self.a_frame = gtk.Expander("Advanced Options")
        self.a_box = gtk.VBox()
        self.a_frame.add(self.a_box)
        self.recursive_button = gtk.CheckButton("Include sub-directories")
        self.recursive_button.set_active(True)
        self.rescan_check = gtk.CheckButton("Rescan for changes after opening")
        self.rescan_check.set_active(True)
        self.load_meta_check = gtk.CheckButton("Load metadata")
        self.load_meta_check.set_active(True)
        self.monitor_images_check = gtk.CheckButton(
            "Monitor image folders for changes")
        self.monitor_images_check.set_active(True)
        self.use_internal_thumbnails_check = gtk.CheckButton(
            "Use embedded thumbnails if available")
        self.use_internal_thumbnails_check.set_active(False)
        self.store_thumbs_combo = wb.LabeledComboBox("Thumbnail storage", [
                                                     "Gnome Desktop Thumbnail Cache (User's Home)",
                                                     "Hidden Folder in Collection Folder"])
        if settings.is_windows:
            self.store_thumbs_combo.set_sensitive(False)
            self.store_thumbs_combo.set_form_data(1)
        else:
            self.store_thumbs_combo.set_form_data(0)
        self.trash_location_combo = wb.LabeledComboBox("Trash Location", [
                                                       "User's Trash Folder",
                                                       "Hidden .trash Folder in Collection Folder"])
        self.trash_location_combo.set_form_data(0)
        self.store_thumbnails_check = gtk.CheckButton(
            "Store thumbnails in cache")
        self.store_thumbnails_check.set_active(True)
        self.store_thumbnails_check.connect(
            "clicked", self.store_thumbnails_clicked)
        self.sidecar_check = gtk.CheckButton(
            "Use metadata sidecars for unsupported formats")
        self.sidecar_check.set_active(False)
        self.a_box.pack_start(self.recursive_button, False)
        self.a_box.pack_start(self.rescan_check, False)
        self.a_box.pack_start(self.monitor_images_check, False)
        self.a_box.pack_start(self.load_meta_check, False)
        self.a_box.pack_start(self.sidecar_check, False)
        self.a_box.pack_start(self.use_internal_thumbnails_check, False)
        self.a_box.pack_start(self.store_thumbnails_check, False)
        self.a_box.pack_start(self.store_thumbs_combo, False)
        self.a_box.pack_start(self.trash_location_combo, False)
        self.pack_start(self.a_frame, False)
        self.show_all()
        if value_dict:
            self.set_values(value_dict)

    def store_thumbnails_clicked(self, toggle):
        self.store_thumbs_combo.set_sensitive(toggle.get_active())

    def path_changed(self, entry):
        sensitive = len(self.name_entry.get_text().strip()) > 0 and os.path.exists(
            self.path_entry.get_path())  # todo: also check that name is a valid filename

    def name_changed(self, entry):
        sensitive = len(entry.get_text().strip()) > 0 and os.path.exists(
            self.path_entry.get_path())  # todo: also check that name is a valid filename

    def get_values(self):
        return {
            'name': self.name_entry.get_text().replace('/', '').strip(),
            'image_dirs': [self.path_entry.get_path()],
            'recursive': self.recursive_button.get_active(),
            'rescan_at_open': self.rescan_check.get_active(),
            'load_meta': self.load_meta_check.get_active(),
            'load_embedded_thumbs': self.use_internal_thumbnails_check.get_active(),
            'load_preview_icons': (self.use_internal_thumbnails_check.get_active()
                                   and not self.load_meta_check.get_active()),
            'monitor_image_dirs': self.monitor_images_check.get_active(),
            'trash_location': ('OPEN-DESKTOP' if self.trash_location_combo.get_form_data() == 0
                               else None),
            'store_thumbnails': self.store_thumbnails_check.get_active(),
            'store_thumbs_with_images': self.store_thumbs_combo.get_form_data(),
            'use_sidecars': self.sidecar_check.get_active(),
        }

    def set_values(self, val_dict):
        self.name_entry.set_text(val_dict['name'])
        if len(val_dict['image_dirs']) > 0:
            self.path_entry.set_path(val_dict['image_dirs'][0])
        self.recursive_button.set_active(val_dict['recursive'])
        self.rescan_check.set_active(val_dict['rescan_at_open'])
        self.load_meta_check.set_active(val_dict['load_meta'])
        self.use_internal_thumbnails_check.set_active(
            val_dict['load_embedded_thumbs'])
        self.monitor_images_check.set_active(val_dict['monitor_image_dirs'])
        self.store_thumbnails_check.set_active(val_dict['store_thumbnails'])
        self.store_thumbs_combo.set_form_data(
            val_dict['store_thumbs_with_images'])
        self.trash_location_combo.set_form_data(
            0 if val_dict['trash_location'] is not None else 1)
        self.sidecar_check.set_active(val_dict['use_sidecars'])



class NewThemeWidget(gtk.VBox):
    def __init__(self, main_dialog, value_dict):
        gtk.VBox.__init__(self)
        
        self.main_dialog = main_dialog
        
        label = gtk.Label()
        label.set_markup("<b>Webalbums Settings</b>")
        
        self.pack_start(label, False)
        box, self.name_entry = dialogs.box_add(self, [(gtk.Entry(), True, None)],'Theme Name: ')
        self.name_entry.connect("changed", self.name_changed)
        self.show_all()

        if value_dict:
            self.set_values(value_dict)

    def activate(self):
        sensitive = len(self.name_entry.get_text().strip()) > 0 ##todo: also check that name is a valid filename
        self.main_dialog.create_button.set_sensitive(sensitive)

    def name_changed(self,entry):
        ##todo: also check that name is valid
        sensitive = len(self.name_entry.get_text().strip()) > 0 
        self.main_dialog.create_button.set_sensitive(sensitive)

    def get_values(self):
        return {
            'name': self.name_entry.get_text().strip()
            }

    def set_values(self,val_dict):
        self.name_entry.set_text(val_dict['name'])

class WalkWebAlbumThemeJob(backend.WorkerJob):
    '''this walks the collection directory adding new items to the collection (but not to the view)'''
    def __init__(self, worker, collection, browser):
        backend.WorkerJob.__init__(self, 'WALKDIRECTORY', 700, worker, collection, browser)
        self.collection_walker = None
        self.notify_items = []
        self.done = False
        self.last_walk_state = None
        self.do_login = True
        
    def _walk_albums(self):
        
        if self.do_login:
            self.collection._login()
        
        first_album_page = wad_tools.get_an_albumSet(parse_and_transform=True, save=False)
        
        if first_album_page is None:
            log.critical("Couldn't fetch albums page")
            raise Exception("Couldn't fetch albums page")
        
        # page = first_album_page.find("albums").find("display").find("albumList").find("page")
        
        # if page.get("last") is not None:
        #     nb_album_pages = int(page.get("last"))
        # elif page.find("next") is not None:
        #     nb_album_pages = int(page.find("next[last()]").text)
        # else:
        #     nb_album_pages = 0
        
        for album in first_album_page.find("albums").find("display").find("albumList").findall("album"):
            album_id = album.get("id")

            album_name = album.find("name").text

            first_photo_page = wad_tools.get_a_photoSet(album_id, name=album_name, full=False)

            if first_photo_page is None:
                msg = "Couldn't fetch photo page for album {}".format(album_id, album_name)
                log.critical(msg)
                raise Exception(msg)

            page = first_photo_page.find("photos").find("display").find("photoList").find("page")
            if page.get("last") is not None:
                nb_photo_pages = int(page.get("last"))
            elif page.find("next") is not None:
                nb_photo_pages = int(page.find("next[last()]").text)
            else:
                nb_photo_pages = 0

            photos = first_photo_page.find("photos").find("display").find("photoList")

            for photo in photos.findall("photo"):
                yield photo
            
    def __call__(self):
        collection = self.collection
        jobs = self.worker.jobs
        self.last_update_time = time.time()
        try:
            if not self.collection_walker:
                log.info('Starting WebAlbums theme walk on %s', collection.name)
                self.collection_walker = self._walk_albums()
                self.done = False
                pluginmanager.mgr.suspend_collection_events(self.collection)
                
        except StopIteration:
            self.notify_items = []
            self.collection_walker = None
            log.error('Aborted directory walk on %s', collection.image_dirs[0])
            return True

        while jobs.ishighestpriority(self):

            backend.idle_add(self.browser.update_backstatus, True, 'Scanning for new images')
            
            while jobs.ishighestpriority(self):
                photo = self.collection_walker.next()
                #print(photo)
                #import_pdb_set_trace()
                
                path = photo.find("details").find("photoId").text
                r = path.rfind('.')
                if r <= 0:
                    continue

                ROOT=
                fullpath = "/var/webalbums/images/"+path
                
                #relpath = os.path.relpath(os.path.join(root, path), scan_dir)
                mimetype = io.get_mime_type(fullpath)
                
                mtime = io.get_mtime(fullpath)
                st = os.stat(fullpath)
                
                item = baseobjects.Item(path)
                item.mtime = mtime
                
                if collection.find(item) < 0:
                    if not collection.verify_after_walk:
                        if collection.load_meta:
                            collection.load_metadata(item, notify_plugins=False)
                        elif collection.load_preview_icons:
                            collection.load_thumbnail(item)
                            if not item.thumb:
                                item.thumb = False
                                
                        self.browser.lock.acquire()
                        collection.add(item)
                        self.browser.lock.release()
                        
                        backend.idle_add(self.browser.resize_and_refresh_view, self.collection)
                    else:
                        self.notify_items.append(item)
                        
            # once we have found enough items, add to collection and notify browser
            if time.time() > self.last_update_time+1.0 or len(self.notify_items) > 100:
                self.last_update_time = time.time()
                
                self.browser.lock.acquire()
                for item in self.notify_items:
                    collection.add(item, False)
                self.browser.lock.release()
                
                backend.idle_add(self.browser.resize_and_refresh_view, self.collection)
                self.notify_items = []
                
        if not self.done:
            return False
    
        log.info('Directory walk complete for {}'.format(collection.image_dirs[0]))
            
        backend.idle_add(self.browser.resize_and_refresh_view, self.collection)
        backend.idle_add(self.browser.update_backstatus, False, 'Search complete')
            
        if self.notify_items:
            self.browser.lock.acquire()
            for item in self.notify_items:
                collection.add(item)
            self.browser.lock.release()
                
            backend.idle_add(self.browser.resize_and_refresh_view, self.collection)
                
        self.notify_items = []
        self.collection_walker = None
        self.done = False
            
        pluginmanager.mgr.resume_collection_events(self.collection)
            
        if collection.verify_after_walk:
            self.worker.queue_job_instance(VerifyImagesJob(self.worker, self.collection, self.browser))
            
        self.collection_walker = None

        return True
               
    
class LoadWebAlbumsThemeJob(backend.WorkerJob):
    def __init__(self, worker, collection, browser, filename=''):
        backend.WorkerJob.__init__(self, 'LOADCOLLECTION', 890, worker, collection, browser)
        self.collection_file = filename
        self.pos = 0

    def __call__(self):
        jobs = self.worker.jobs
        jobs.clear(None, self.collection, self)
        view = self.collection.get_active_view()
        collection = self.collection
        
        log.info('Loading collection file %s with type %s', self.collection_file, collection.type)
        
        backend.idle_add(self.browser.update_backstatus, True, 'Loading Collection: %s' % (self.collection_file,))
        view.empty()
        
        pluginmanager.mgr.callback('t_view_emptied',collection,view)
        
        if collection._open():
            log.info('Collection opened %s', collection.id)
            
            collection.online = True
            self.worker.queue_job_instance(WalkWebAlbumThemeJob(self.worker,self.collection,self.browser))
            WalkWebAlbumThemeJob(self.worker,self.collection,self.browser)()
            
            pluginmanager.mgr.callback_collection('t_collection_loaded',collection)
            
            if not view.loaded:
                self.worker.queue_job_instance(backend.BuildViewJob(self.worker, self.collection, self.browser))
            else:
                pluginmanager.mgr.callback('t_view_updated', collection, view)
                
                
            backend.idle_add(self.worker.coll_set.collection_opened, collection.id)
                
            log.info('Loaded collection with {} images'.format(len(collection)))
        else:
            log.error('Load collection failed %s %s', collection.id, collection.type)
            
        self.collection_file = ''
        
        return True

        
class Theme(baseobjects.CollectionBase):
    '''
    Defines a webalbums theme
    '''
    type = 'WEBALBUMS'
    type_descr = 'WebAlbums Theme'
    local_filesystem = True
    pref_widget = LocalStorePrefWidget
    add_widget = NewThemeWidget
    metadata_widget = dialogs.MetaDialog
    transfer_widget = LocalTransferOptionsBox
    browser_sort_keys = viewsupport.sort_keys
    persistent = True
    user_creatable = True
    view_class = simpleview.SimpleView
    pref_items = baseobjects.CollectionBase.pref_items + ('image_dirs',
                                                          'recursive',
                                                          'load_meta',
                                                          'load_preview_icons',
                                                          'monitor_image_dirs',
                                                          'use_sidecars')

    def __init__(self, prefs):  # todo: store base path for the collection
        # the following attributes are set at run-time by the owner
        baseobjects.CollectionBase.__init__(self)

        self.index = baseobjects.MetadataIndex()

        # the collection consists of an array of entries for images,
        # which are cached in the collection file
        self.items = []  # the image/video items

        # and has the following properties (which are stored in the collection
        # file if it exists)
        
        self.use_sidecars = False

        # the collection optionally has a filesystem monitor and views (i.e.
        # subsets) of the collection of images
        self.monitor = None
        self.monitor_master_callback = None
        self.browser = None
        self.online = False

        self.choix = None
        
        if prefs:
            self.set_prefs(prefs)

        self.id = self.name

    ''' ************************************************************************
                            PREFERENCES, OPENING AND CLOSING
        ************************************************************************'''

    def set_prefs(self, prefs):
        baseobjects.CollectionBase.set_prefs(self, prefs)

    def connect(self):
        if not self.is_open:
            return False
        if self.online:
            return False
        self.online = True
        return True

    def disconnect(self):
        if not self.is_open:
            return False
        self.online = False
        return True

    def delete_store(self):
        log.info('WA them {} created'.format(self.name))
        return True
    

    def create_store(self):
        log.info('New WA theme created: {}'.format(self.name))
        pass

    def _login(self):
        try:
            
            wad_tools.login("kevin", "", save_index=False,
                            do_static=False, get_xslt=False,
                            parse_and_transform=True)
            wad_tools.get_index(do_static=True)
            self.choix = wad_tools.get_choix(9, name="Grenoble", want_static=False,
                                             want_background=False,
                                             save=False, parse_and_transform=True)
            return True
        except Exception as e:
            log.critical("Could not loging into WebAlbums server: {}".format(e))
            return False

    def open(self, thread_manager, browser=None):
        log.info('Open {} theme '.format(self.name))

        try:
            with open(self.data_file(),'rb') as data_f:
                log.warn("read {} from {}".format(data_f.readlines(),
                                                  self.data_file()))

            self.load_prefs()
        except IOError as e:  # could not open/read
            log.critical("Could not load collection '{}' from file: {}".format(self.name, e))
            
        
        job = LoadWebAlbumsThemeJob(thread_manager, self, browser)
        thread_manager.queue_job_instance(job)
        
    def _open(self):
        '''
        load the collection from a binary pickle file
        '''

        log.info('_load from pickle {} theme '.format(self.name))
        return True

    def close(self):
        '''
        save the collection to a binary pickle file using the filename attribute of the collection
        '''
        log.info('Close {} theme '.format(self.name))
        col_dir = self.coll_dir()

        if not os.path.exists(col_dir):
            os.makedirs(col_dir)
            
        with open(self.data_file(), 'wb') as fdata:
            fdata.write(self.name)
            
        log.warn("saved {} into {}".format(self.name, self.data_file()))
        self.save_prefs()
        
        return True

    def rescan(self, thead_manager):
        log.info('Rescan {} theme '.format(self.name))
        #sj = backend.WalkDirectoryJob(thead_manager, self, self.browser)
        #thead_manager.queue_job_instance(sj)

    ''' ************************************************************************
                            MANAGING THE LIST OF COLLECTION ITEMS
        ************************************************************************'''

    def add(self, item, add_to_view=True):
        '''
        add an item to the collection and notify plugin
        '''
        log.info('Adding {} to collection {}'.format(item, self))
        return False

    def delete(self, item, delete_from_view=True):
        '''
        delete an item from the collection, returning the item to the caller if present
        notifies plugins if the item is remmoved
        '''
        i = self.find(item)
        log.info('Removing {} from collection {}'.format(item, self))

        return None

    def find(self, item):
        '''
        find an item in the collection and return its index
        '''
        log.info('Find {} from collection {}'.format(item, self))

        return -1

    def get_mtime(self, item):
        log.info('mtime {} from collection {}'.format(item, self))

        return io.get_mtime(self.get_path(item))

    def get_path(self, item):
        '''
        returns the full path associated with the item
        beware that this uses the hack that the item is derived from str
        and the content of the string is the uid
        '''
        log.info('Path of {} from collection {}'.format(item, self))
        return os.path.join(self.image_dirs[0], item)

    def item_exists(self, item):
        log.info('Exists {} from collection {}'.format(item, self))
        
        return os.path.exists(self.get_path(item))

    def get_relpath(self, path):
        log.info('Relpath of {} from collection {}'.format(path, self))
        return os.path.relpath(path, self.image_dirs[0])

    def __str__(self):
        return "Theme[{}]".format(self.name)
    
    def __call__(self, ind):
        log.info('call {} from collection {}'.format(ind, self))
        return self.items[ind]

    def __getitem__(self, ind):
        log.info('Get item {} from collection {}'.format(ind, self))
        return self.items[ind]

    def get_all_items(self):
        log.info('get all items from collection {}'.format(self))
        
        return self.items[:]

    def empty(self, empty_views=True):
        pass

    def __len__(self):
        log.info('get len from collection {}'.format(self))

        return len(self.items)

    ''' ************************************************************************
                            MANIPULATING INDIVIDUAL ITEMS
        ************************************************************************'''

    def copy_item(self, src_collection, src_item, prefs):
        return False

    def delete_item(self, item):
        return False

    def load_thumbnail(self, item, fast_only=True):
        'load the thumbnail from the local cache'
    
        if self.load_preview_icons:
            if imagemanip.load_thumb_from_preview_icon(item, self):
                return True
        if fast_only and not item.thumburi and self.load_embedded_thumbs:
            if imagemanip.load_embedded_thumb(item, self):
                return True
        return imagemanip.load_thumb(item, self, self.thumbnail_cache_dir)

    def has_thumbnail(self, item):
        return imagemanip.has_thumb(item, self, self.thumbnail_cache_dir)

    def make_thumbnail(self, item, interrupt_fn=None, force=False):
        'create a cached thumbnail of the image'
        if not force and (self.load_embedded_thumbs or self.load_preview_icons):
            return False
        imagemanip.make_thumb(item, self, interrupt_fn, force,
                              self.thumbnail_cache_dir, write_to_cache=self.store_thumbnails)
# TODO: Why was the update_thumb_date call here??? Maybe a FAT issue?
# imagemanip.update_thumb_date(item,cache=self.thumbnail_cache_dir)
        return

    def delete_thumbnail(self, item):
        'clear out the thumbnail and delete the file from the users gnome desktop cache'
        imagemanip.delete_thumb(item)

    def rotate_thumbnail(self, item, right=True, interrupt_fn=None):
        '''
        rotates thumbnail of item 90 degrees right (clockwise) or left (anti-clockwise)
        right - rotate right if True else left
        interrupt_fn - callback that returns False if job should be interrupted
        '''
        if item.thumb == False:
            return False
        thumb_pb = imagemanip.rotate_thumb(item, right, interrupt_fn)
        if not thumb_pb:
            return False
        item.thumb = thumb_pb
        imagemanip.cache_thumb_in_memory(item)
        uri = io.get_uri(self.get_path(item))
        if self.thumbnail_cache_dir == None:
            imagemanip.thumb_factory.save_thumbnail(
                thumb_pb, uri, int(item.mtime))
            item.thumburi = imagemanip.thumb_factory.lookup(
                uri, int(item.mtime))
        else:
            cache = self.thumbnail_cache_dir
            if not os.path.exists(cache):
                os.makedirs(cache)
            item.thumb.save(item.thumburi, "png")
        return True

    def item_metadata_update(self, item, old_metadata):
        'collection will receive this call when item metadata has been changed'
        if self.index:
            self.index.update(item, old_metadata)

    def load_metadata(self, item, missing_only=False, notify_plugins=True):
        'retrieve metadata for an item from the source'
        if self.load_embedded_thumbs:
            result = imagemanip.load_metadata(item, collection=self, filename=self.get_path(item),
                                              get_thumbnail=True, missing_only=missing_only,
                                              check_for_sidecar=self.use_sidecars,
                                              notify_plugins=notify_plugins)
        else:
            result = imagemanip.load_metadata(item, collection=self, filename=self.get_path(item),
                                              get_thumbnail=False, missing_only=missing_only,
                                              check_for_sidecar=self.use_sidecars,
                                              notify_plugins=notify_plugins)
        if self.load_embedded_thumbs and not item.thumb:
            item.thumb = False
        return result

    def write_metadata(self, item):
        'write metadata for an item to the source'
        return imagemanip.save_metadata(item, self, cache=self.thumbnail_cache_dir,
                                        sidecar_on_failure=self.use_sidecars)

    def load_image(self, item, interrupt_fn=None, size_bound=None, apply_transforms=True):
        'load the fullsize image, up to maximum size given by the (width, height) tuple in size_bound'
        draft_mode = False
        return imagemanip.load_image(item, self, interrupt_fn, draft_mode,
                                     apply_transforms=apply_transforms)

    def get_file_stream(self, item):
        'return a stream read the entire photo file from the source (as binary stream)'
        return open(self.get_path(item), 'rb')

    def write_file_data(self, dest_item, src_stream):
        log.info('write file data {}'.format(dest_item))
        return False
    
        'write the entire photo file (as a stream) to the dest_item (as binary stream)'
        try:
            f = open(self.get_path(dest_item), 'wb')
            f.write(src_stream.read())
            f.close()
            return True
        except:
            log.warn('Error writing file data: {}'.format(dest_item))

    def get_browser_text(self, item):
        header = ''
        if settings.overlay_show_title:
            try:
                header = item.meta['Title']
            except:
                header = os.path.split(item.uid)[1]
        details = ''
        if settings.overlay_show_path:
            details += os.path.split(self.get_path(item))[0]
        if settings.overlay_show_tags:
            val = viewsupport.get_keyword(item)
            if val:
                if details and not details.endswith('\n'):
                    details += '\n'
                val = str(val)
                if len(val) < 90:
                    details += 'Tags: ' + val
                else:
                    details += val[:88] + '...'
        if settings.overlay_show_date:
            val = viewsupport.get_ctime(item)
            if val > datetime(1900, 1, 1):
                if details and not details.endswith('\n'):
                    details += '\n'
                details += 'Date: ' + str(val)
    #    else:
    #        details+='Mod: '+str(get_mtime(item))
        if settings.overlay_show_exposure:
            val = viewsupport.get_focal(item)
            exposure = u''
            if val:
                exposure += '%imm ' % (int(val),)
            val = viewsupport.get_aperture(item)
            if val:
                exposure += 'f/%3.1f' % (val,)
            val = viewsupport.get_speed_str(item)
            if val:
                exposure += ' %ss' % (val,)
            val = viewsupport.get_iso_str(item)
            if val:
                exposure += ' iso%s' % (val,)
            if exposure:
                if details and not details.endswith('\n'):
                    details += '\n'
                details += exposure
        return (header, details)

    def get_viewer_text(self, item, size=None, zoom=None):
        # HEADER TEXT
        header = ''
        # show title
        path, filename = os.path.split(self.get_path(item))
        try:
            header = item.meta['Title']
            title = True
        except:
            header += filename
            title = False

        # DETAIL TEXT
        details = ''
        # show filename and path to image
        if title:
            details += filename + '\n'
        details += path
        # show tags
        val = viewsupport.get_keyword(item)
        if val:
            if details and not details.endswith('\n'):
                details += '\n'
            val = str(val)
            if len(val) < 90:
                details += 'Tags: ' + val
            else:
                details += val[:88] + '...'
        # date information
        if details and not details.endswith('\n'):
            details += '\n'
        val = viewsupport.get_ctime(item)
        if val > datetime(1900, 1, 1):
            details += 'Date: ' + str(val) + '\n'
    ###    details+='Date Modified: '+str(get_mtime(item))
        if item.meta != None and 'Model' in item.meta:
            details += 'Model: ' + str(item.meta['Model']) + '\n'
        # Exposure details
        val = viewsupport.get_focal(item)
        exposure = u''
        if val:
            exposure += '%imm ' % (int(val),)
        val = viewsupport.get_aperture(item)
        if val:
            exposure += 'f/%3.1f' % (val,)
        val = viewsupport.get_speed_str(item)
        if val:
            exposure += ' %ss' % (val,)
        val = viewsupport.get_iso_str(item)
        if val:
            exposure += ' iso%s' % (val,)
        if exposure:
            if details and not details.endswith('\n'):
                details += '\n'
            details += 'Exposure: ' + exposure
        # IMAGE SIZE AND ZOOM LEVEL
        if size:
            if details and not details.endswith('\n'):
                details += '\n'
            details += 'Image Dimensions: %i x %i' % size
        if zoom:
            if details and not details.endswith('\n'):
                details += '\n'
            if zoom != 'fit':
                details += 'Zoom: %3.2f%%' % (zoom * 100,)
            else:
                details += 'Zoom: Fit'

        return (header, details)

log.setLevel(logging.DEBUG)
baseobjects.register_collection('WEBALBUMS', Theme)
log.warn("WebAlbums themes registered.")

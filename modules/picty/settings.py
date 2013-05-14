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

##picty global settings
import os
import cPickle
import Image
import gtk

release_version='0.4' #this is the version number of the released program
version='0.6.1' #version is saved to data and configuration files
#version notes:
# 0.6.0
#  * separated preferences and image data cache into separate files (under collection name directory)
# 0.5.0
#  * dropped compatibility with Keyword stored as tuple
#  * dropped thumbsize, qview_size, thumbrgba, cannot_thumb members of image


plugins_disabled=[]

max_memthumbs=1000
max_memimages=3
precache_count=500 ##not currently used

#custom launchers (tools) available from right click menu in browser
#tools understand the following variable substituions:
#$FULLPATH,$DIR,$FULLNAME,$NAME,$EXT
custom_launchers={
'image/jpeg':[('GIMP','gimp "$FULLPATH"'),],
'image/png':[('GIMP','gimp "$FULLPATH"'),],
'image/x-pentax-pef':[('UFRaw','ufraw "$FULLPATH"'),],
'default':[('Nautilus','nautilus "$DIR"'),],
}

layout={}  #the layout of the user interface

edit_command_line='gimp'
dcraw_cmd='/usr/bin/dcraw -e -c "%s"'
dcraw_backup_cmd='/usr/bin/dcraw -T -h -w -c "%s"'
raw_image_types = {
'image/x-adobe-dng':[dcraw_cmd],
'image/x-canon-crw':[dcraw_cmd],
'image/x-canon-cr2':[dcraw_cmd],
'image/x-nikon-nef':[dcraw_cmd],
'image/x-pentax-pef':[dcraw_cmd],
'image/x-olympus-orf':[dcraw_cmd],
}
video_thumbnailer='totem-video-thumbnailer -j "%s" /dev/stdout'


imagetypes=['jpg','jpeg','png']

home_dir = os.path.expanduser("~")

def get_user_dir(env_var,alt_path,sub_dir=''):
    try:
        path=os.path.join(os.environ[env_var],'picty')
        if sub_dir:
            path=os.path.join(path,sub_dir)
    except KeyError:
        path=os.path.join(os.path.expanduser("~"),alt_path)
        if sub_dir:
            path=os.path.join(path,sub_dir)
    if not os.path.exists(path):
        os.makedirs(path)
    return path

import platform
if platform.system() == 'Windows':
    settings_dir=get_user_dir('APPDATA','.picty','settings')
    data_dir=get_user_dir('APPDATA','.picty','data')
    cache_dir=get_user_dir('APPDATA','.picty','cache') ##todo: not using cache yet. parts of the collection are definitely cache
    is_windows=True
else:
    settings_dir=get_user_dir('XDG_CONFIG_HOME','.config/picty')
    data_dir=get_user_dir('XDG_DATA_HOME','.local/share/picty')
    cache_dir=get_user_dir('XDG_CACHE_HOME','.cache/') ##todo: not using cache yet. parts of the collection are definitely cache
    is_windows=False

overlay_show_title=True
overlay_show_path=False
overlay_show_tags=True
overlay_show_date=True
overlay_show_exposure=True

active_collection=None
active_collection_id=''
collections_dir=''
default_collection_file=''
legacy_collection_file=''
legacy_collection_file2=''
conf_file=''
legacy_conf_file=os.path.join(home_dir,'.picty-settings')
legacy_image_dirs=[]


def init_settings_files():
    global collections_dir, default_collection_file, legacy_collection_file, legacy_collection_file2, conf_file, settings_dir, data_dir

    collections_dir=os.path.join(data_dir,'collections')
    if not os.path.exists(collections_dir):
        os.makedirs(collections_dir)

    default_collection_file=os.path.join(collections_dir,'collection') ##todo: support multiple collections
    legacy_collection_file=os.path.join(home_dir,'.picty-collection')
    legacy_collection_file2=os.path.join(data_dir,'collection')
    if not os.path.exists(default_collection_file):
        if os.path.exists(legacy_collection_file2):
            os.renames(legacy_collection_file2,default_collection_file)
        elif os.path.exists(legacy_collection_file):
            os.renames(legacy_collection_file,default_collection_file)

    conf_file=os.path.join(settings_dir,'app-settings')

def save():
    global version, precache_count, custom_launchers, user_tag_info, places, active_collection_id
    try:
        f=open(conf_file,'wb')
    except:
        print 'Error saving settings'
        import sys,traceback
        tb_text=traceback.format_exc(sys.exc_info()[2])
        print tb_text
        return False
    try:
        cPickle.dump(version,f,-1)
        cPickle.dump(active_collection_id,f,-1)
        cPickle.dump(precache_count,f,-1)
        cPickle.dump(layout,f,-1)
        cPickle.dump(custom_launchers,f,-1)
        cPickle.dump(plugins_disabled,f,-1)
        cPickle.dump(overlay_show_title,f,-1)
        cPickle.dump(overlay_show_path,f,-1)
        cPickle.dump(overlay_show_tags,f,-1)
        cPickle.dump(overlay_show_date,f,-1)
        cPickle.dump(overlay_show_exposure,f,-1)
    finally:
        f.close()


def load():
    global version, precache_count, custom_launchers, user_tag_info, places, layout, \
        active_collection_id, legacy_image_dirs, plugins_disabled, \
        overlay_show_title,overlay_show_path,overlay_show_tags,overlay_show_date,overlay_show_exposure
    try:
        f=open(conf_file,'rb')
    except:
        try:
            print 'loading legacy config file'
            f=open(legacy_conf_file,'rb')
        except:
            return False
    try:
        file_version=cPickle.load(f)
        if file_version>='0.3.2':
            active_collection_id=os.path.split(cPickle.load(f))[1]
        if file_version<'0.3.0':
            legacy_image_dirs=cPickle.load(f)
        if file_version<='0.3.1':
            store_thumbs=cPickle.load(f)
        precache_count=cPickle.load(f)
        if file_version>='0.3.1':
            layout=cPickle.load(f)
        if file_version>='0.3.0':
            custom_launchers=cPickle.load(f)
            for c in custom_launchers:
                custom_launchers[c]=list(custom_launchers[c])
        else:
            if file_version>='0.2.3':
                user_tag_info=cPickle.load(f)
                custom_launchers=cPickle.load(f)
                for c in custom_launchers:
                    custom_launchers[c]=list(custom_launchers[c])
            if file_version>='0.2.4':
                places=cPickle.load(f)
        if file_version>='0.3.2':
            plugins_disabled=cPickle.load(f)
        if file_version>='0.4.2':
            overlay_show_title=cPickle.load(f)
            overlay_show_path=cPickle.load(f)
            overlay_show_tags=cPickle.load(f)
            overlay_show_date=cPickle.load(f)
            overlay_show_exposure=cPickle.load(f)
    except:
        pass
    finally:
        f.close()


def user_add_dir():
    image_dirs=[]
    fcd=gtk.FileChooserDialog(title='Choose Photo Directory', parent=None, action=gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
        buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK), backend=None)
    fcd.set_current_folder(home_dir)
    response=fcd.run()
    if response == gtk.RESPONSE_OK:
        image_dirs.append(fcd.get_filename())
    fcd.destroy()
    return image_dirs


def init():
    init_settings_files()
    global image_dirs, active_collection_id
    load()
    if not active_collection_id:
        try:
            active_collection_id=get_collection_files()[0]
        except:
            active_collection_id=''
    save()


def get_collection_files():
    return os.listdir(collections_dir)
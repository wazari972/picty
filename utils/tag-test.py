#!/usr/bin/python

'''

    pyexiv2_viewer
    Copyright (C) 2013  Damien Moore
    parts of main program (C) 2010 Olivier Tilloy

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

import os.path
import sys
import gtk
import pyexiv2
import pango
from phraymd import settings

def file_dialog(title='Choose an Image',default=''):
    '''
    simple file selector dialog
    '''
    fcd=gtk.FileChooserDialog(title=title, parent=None, action=gtk.FILE_CHOOSER_ACTION_OPEN,
        buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK), backend=None)
    if not default:
        default=settings.home_dir
    fcd.set_current_folder(default)
    response=fcd.run()
    image_dir=''
    if response == gtk.RESPONSE_OK:
        image_dir=fcd.get_filename()
    fcd.destroy()
    return image_dir


def create_key_tree(key_list):
    '''
    builds a tree structure (nested python dicts) from an underlying list of metadata keys
    '''
    tree={} #todo: use a sorted dict
    for key in key_list:
        sub_tree=tree
        key=key.split('.')
        for node in key:
            if node in sub_tree:
                sub_tree=sub_tree[node]
                continue
            sub_tree[node]={}
            sub_tree=sub_tree[node]
    return tree

class MetadataModel3(gtk.TreeStore):
    '''
    TreeModel for image metadata
    Copies metadata keys from the pyexiv2 ImageMetadata into a TreeStore for display in a TreeView

    to be implemented: displaying all standard keys in the standard (not just the ones in the image)
    methods for editing metadata then adding/removing/changing rows (notifies associated views)
    '''
    def __init__(self,tag_defs,exiv2metadata=None):
        gtk.TreeStore.__init__(self,str,str,bool,int)
        self.exiv2metadata=exiv2metadata
        self.set_defs(tag_defs)
        self.set_meta(exiv2metadata)
        self.filter=self.filter_new()
        self.filter_text=''
        self.filter_hide_missing=True
        self.filter.set_visible_func(self.is_visible)

    def set_defs(self,tag_defs):
        self.tag_defs=tag_defs
        self.key_list=list(self.tag_defs)
        self.key_list.sort()
        for k in self.key_list:
            self.append(None,[k,'',False,400])
    def clear_defs(self):
        for i in xrange(len(self)):
            if self[i][2]:
                self[i][2]=False
                self[i][3]=400
                self[i][1]=''
    def set_meta(self,exiv2metadata=None):
        self.clear_defs()
        self.exiv2metadata=exiv2metadata
        if self.exiv2metadata==None:
            self.exiv2keys=[]
        else:
            self.exiv2keys=self.exiv2metadata.exif_keys+self.exiv2metadata.iptc_keys+self.exiv2metadata.xmp_keys
        for k in self.exiv2keys:
            value=self.get_key_value(k)
            try:
                path=self.key_list.index(k)
            except ValueError:
                print 'warning: unknown key',k
                continue
            self[path]=[k,value,True,800]
    def get_key_value(self,key):
        key_type=key.split('.').pop(0)
        if key_type=='Exif':
            try:
                value=self.exiv2metadata[key].human_value
            except:
                value=self.exiv2metadata[key].value
        elif key_type=='Iptc':
            value=str(self.exiv2metadata[key].values) ##todo: repeatable values could be nested as separate rows
        elif key_type=='Xmp':
            value=str(self.exiv2metadata[key].value) ##todo: repeated values could be nested as separate rows
#        if len(value)>200:
#            value=value[0:200]+'...'
        return value
    def is_visible(self,model,iter):
        if not self.filter_text or self.filter_text in model[iter][0].lower():
            if not self.filter_hide_missing or model[iter][2]:
                return True
        return False
    def change_filter(text='',hide_missing=True):
        self.filter_text=text.lower()
        self.filter_hide_missing=hide_missing
        self.filter.refilter()

class MetadataModel(gtk.TreeStore):
    '''
    TreeModel for image metadata
    Copies metadata keys from the pyexiv2 ImageMetadata into a TreeStore for display in a TreeView

    to be implemented: displaying all standard keys in the standard (not just the ones in the image)
    methods for editing metadata then adding/removing/changing rows (notifies associated views)
    '''
    def __init__(self,exiv2metadata=None):
        gtk.TreeStore.__init__(self,str,str,bool)
        self.exiv2metadata=exiv2metadata
        self.key_tree={}
        if exiv2metadata:
            self.set_meta(exiv2metadata)
    def set_meta(self,exiv2metadata):
        self.clear()
        self.exiv2metadata=exiv2metadata
        keys=exiv2metadata.exif_keys+exiv2metadata.iptc_keys+exiv2metadata.xmp_keys
        self.key_tree=create_key_tree(keys) #convert the "dotted" key list to a tree (actually nested dictionaries)
        self.add_rows('',None,self.key_tree)
    def as_row(self,key):
        name=key.split('.').pop()
        try:
            key_type=key.split('.').pop(0)
            if key_type=='Exif':
                try:
                    value=self.exiv2metadata[key].human_value
                except:
                    value=self.exiv2metadata[key].value
            elif key_type=='Iptc':
                value=str(self.exiv2metadata[key].values) ##todo: repeatable values could be nested as separate rows
            elif key_type=='Xmp':
                value=str(self.exiv2metadata[key].value) ##todo: repeated values could be nested as separate rows
        except:
            value=''
        return [name,value,False]
    def add_rows(self,parent_key,iter,tree):
        for k in tree:
            if parent_key:
                key=parent_key+'.'+k
            else:
                key=k
            ch_iter=self.append(iter,self.as_row(key))
            self.add_rows(key,ch_iter,tree[k])


class MetadataModel2(gtk.GenericTreeModel):
    '''
    TreeModel for image metadata

    This version derives from gtk.GenericTreeModel allowing user interaction with image metadata as a gtk.TreeView
    Most of the methods below are required for implementing gtk.TreeModel (see pygtk tutorial)

    to be implemented: displaying all standard keys in the standard (not just the ones in the image)
    methods for editing metadata then adding/removing/changing rows (notifies associated views)
    '''
    def __init__(self,exiv2metadata=None):
        gtk.GenericTreeModel.__init__(self)
        self.exiv2metadata=exiv2metadata
        self.n_columns=3
        self.col_types=(str,str,bool)  #key, value, editable
        self.key_tree={}
        if exiv2metadata:
            self.set_meta(exiv2metadata)
    def set_meta(self,exiv2metadata):
        self.clear()
        self.exiv2metadata=exiv2metadata
        keys=exiv2metadata.exif_keys+exiv2metadata.iptc_keys+exiv2metadata.xmp_keys
        self.key_tree=create_key_tree(keys) #convert the "dotted" key list to a tree (actually nested dictionaries)
        for k in self.iter_tree(self.key_tree):
            self.row_inserted(*self.pi_from_id(k))
    def clear(self):
        for x in range(len(self.key_tree)):
            self.row_deleted((0,))
        self.exiv2metadata=None
        self.key_tree={}
    def iter_tree(self,tree,parentkey=''):
        for node in tree:
            if parentkey:
                key=parentkey+'.'+node
            else:
                key=node
            yield key
            for child_key in self.iter_tree(tree[node],key):
                yield child_key
    def on_get_flags(self):
        return gtk.TREE_MODEL_ITERS_PERSIST
    def on_get_n_columns(self):
        return self.n_columns
    def on_get_column_type(self, index):
        return self.col_types[index]
    def on_get_iter(self, path):
        sub_tree=self.key_tree
        key=[]
        for p in path:
            try:
                node=list(sub_tree)[p]
            except IndexError:
                return None
            key.append(node)
            sub_tree=sub_tree[node]
        return '.'.join(key)
    def on_get_path(self, key):
        key=key.split('.')
        sub_tree=self.key_tree
        path=[]
        for node in key:
            ind=list(sub_tree).index(node)
            if ind<0:
                return None
            path.append(ind)
            sub_tree=sub_tree[node]
        return tuple(path)
    def on_get_value(self, key, column):
        return self.as_row(key)[column]
    def on_iter_next(self, key):
        key=key.split('.')
        cur=key.pop()
        done=False
        while True:
            subtree=self.get_subtree(key)
            if subtree==None:
                return None
            sub_list=list(subtree)
            ind=sub_list.index(cur)
            if ind<0:
                return None
            else:
                try:
                    next=sub_list[ind+1]
                    key.append(next)
                    return '.'.join(key)
                except IndexError:
                    return None
#                    if len(key)>0:
#                        cur=key.pop()
#                    else:
#                        return None
    def on_iter_children(self, parentkey):
        if not parentkey:
            key=[]
        else:
            key=parentkey.split('.')
        subtree=self.get_subtree(key)
        for node in subtree:
            return '.'.join(key+[node])
        return None
    def on_iter_has_child(self, parentkey):
        if not parentkey:
            key=[]
        else:
            key=parentkey.split('.')
        subtree=self.get_subtree(key)
        return len(subtree)>0
    def on_iter_n_children(self, parentkey):
        if not parentkey:
            key=[]
        else:
            key=parentkey.split('.')
        subtree=self.get_subtree(key)
        if subtree==None:
            return 0
        return len(subtree)
    def on_iter_nth_child(self, parent, n):
        if not parent:
            key=[]
        else:
            key=parent.split('.')
        subtree=self.get_subtree(key)
        if subtree==None:
            return None
        sub_list=list(subtree)
        try:
            nth=sub_list[n]
        except IndexError:
            return None
        return '.'.join(key+[nth])
    def on_iter_parent(self, child):
        ind=child.rfind('.')
        if ind<0:
            return None
        else:
            return child[:ind]
    '''
    helper methods for implementing the tree model methods
    '''
    def get_subtree(self,node_list):
        subtree=self.key_tree
        for node in node_list:
            try:
                subtree=subtree[node]
            except KeyError:
                return None
        return subtree
    def pi_from_id(self,name): #return tuple of path and iter associated with the unique identifier
        iter=self.create_tree_iter(name)
        return self.get_path(iter),iter
    def as_row(self,key):
        name=key.split('.').pop()
        try:
            key_type=key.split('.').pop(0)
            if key_type=='Exif':
                try:
                    value=self.exiv2metadata[key].human_value
                except:
                    value=self.exiv2metadata[key].value
            elif key_type=='Iptc':
                value=str(self.exiv2metadata[key].values) ##todo: repeatable values could be nested as separate rows
            elif key_type=='Xmp':
                value=str(self.exiv2metadata[key].value) ##todo: repeated values could be nested as separate rows
        except:
            value=''
        return [name,value,False]


class MetadataTreeView(gtk.VBox):
    def __init__(self,model):
        gtk.VBox.__init__(self)
        self.model=model
        self.tv=gtk.TreeView(self.model)
        self.tv.set_headers_visible(True)
        self.tv.set_property("rules-hint",True)

        c_key=gtk.CellRendererText()
#        c_key.set_property("ellipsize-set",True)
#        c_key.set_property("ellipsize",pango.ELLIPSIZE_END)
        c_key.set_property('weight-set',True)
        self.tvc_key=gtk.TreeViewColumn("Key",c_key,text=0,weight=3) ##todo: model column indexes shouldn't be hardcoded

        c_value=gtk.CellRendererText()
#        c_value.set_property("ellipsize-set",True)
#        c_value.set_property("ellipsize",pango.ELLIPSIZE_MIDDLE)
        self.tvc_value=gtk.TreeViewColumn("Value(s)",c_value,text=1)

        self.tv.append_column(self.tvc_key)
        self.tv.append_column(self.tvc_value)
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.add(self.tv)
        scrolled_window.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
        self.pack_start(scrolled_window)
        self.set_property("has-tooltip",True)
        self.connect("query-tooltip",self.tooltip_query)
        self.show_all()
    def tooltip_query(self,widget,x, y, keyboard_mode, tooltip):
        path,tvc,cx,cy=self.tv.get_path_at_pos(int(x),int(y))
        if path:
            path=self.model.convert_path_to_child_path(path)
            key=self.model.get_model()[path][0]
            if tvc==self.tvc_key:
                try:
                    desc=self.model.get_model().tag_defs[key].description
                except:
                    desc='Unknown'
            if tvc==self.tvc_value:
                try:
                    try:
                        desc=self.model.get_model().exiv2metadata[key].human_value
                    except:
                        desc=str(self.model.get_model().exiv2metadata[key].value)
                except:
                    desc=''
#            print 'tip',desc
            if desc:
                tooltip.set_text(desc)
            return True


class App(gtk.Window):
    def __init__(self,path,tag_defs):
        gtk.Window.__init__(self,gtk.WINDOW_TOPLEVEL)
        self.connect("destroy",lambda window: gtk.main_quit())

        box=gtk.HBox()

        vbox=gtk.VBox()

        self.path=path

        open_button=gtk.Button("Open...",gtk.STOCK_OPEN)
        open_button.connect("clicked",self.open_button)
        vbox.pack_start(open_button,False,False)

        self.imgwidget = gtk.Image()
        self.imgwidget.show()
        vbox.pack_start(self.imgwidget,False)
        box.pack_start(vbox,False)

        self.model=MetadataModel3(tag_defs,None)
        treeview=MetadataTreeView(self.model.filter)
        box.pack_start(treeview)

        # Add the box to the main window, show everything and start the app
        box.show_all()
        self.add(box)
        self.set_default_size(400,400)
        self.set_title("Metadata Viewer")
        self.show()
        self.open_image(path)

    def run(self):
        gtk.main()

    def open_button(self,button):
        self.open_image()

    def open_image(self,path=''):
        if not path:
            default=''
            if self.path:
                default=os.path.split(self.path)[0]
            path=file_dialog(default=default)
            if not path:
                return
        self.path=os.path.abspath(path)
        # Load the image, read the metadata
        try:
            metadata = pyexiv2.ImageMetadata(self.path)
            metadata.read()
        except:
            self.imgwidget.clear()
            self.model.clear()
            self.set_title("Metadata Viewer")
            return

        self.set_title("Metadata Viewer - %s"%(path,))
        #extract the thumbnail data
        previews = metadata.previews
        if previews:
            preview = previews[-1]
            # Get the largest preview available
            # Create a pixbuf loader to read the thumbnail data
            pbloader = gtk.gdk.PixbufLoader()
            pbloader.write(preview.data)
            pixbuf = pbloader.get_pixbuf()
            pbloader.close()
            scale=200.0/max(pixbuf.get_width(),pixbuf.get_height())
            if scale<1:
                w=int(pixbuf.get_width()*scale)
                h=int(pixbuf.get_height()*scale)
                pixbuf=pixbuf.scale_simple(w,h,gtk.gdk.INTERP_BILINEAR)
            self.imgwidget.set_from_pixbuf(pixbuf)
        print 'setting model metadata',metadata
        self.model.set_meta(metadata)


class TagObject(object):
    def __init__(self,key_list,value_list,tag_type):
        for x in xrange(len(key_list)):
            try:
                self.__dict__[key_list[x].strip()]=value_list[x].strip()
            except:
                print 'error in',x,key_list[x],value_list
        self.tag_type=tag_type
    def __repr__(self):
        return '<TagObject %s>'%(self.key,)

def TagObject_from_xmp_data(key_list,value_list,schema):
    t=TagObject(key_list,value_list,'xmp')
    t.schema=schema
    t.key='xmp.%s.%s'%(schema,t.property)
    return t


'''
exif
Tag (hex) 	Tag (dec) 	IFD 	Key 	Type 	Tag description
iptc
Tag (hex) 	Tag (dec) 	Key 	Type 	M. 	R. 	Min. bytes 	Max. bytes 	Tag description
xmp
Property 	Label 	Value type 	Exiv2 type 	Category 	Description
'''

def get_tag_info():
    tag_objects={}

    f=open("exif-tags","r")
    data=f.read()
    lines=data.split('\n')
    key=lines.pop(0).split('\t')
    key='tag_hex,tag_dec,ifd,key,type,description'.split(',')
    for l in lines:
        if l:
            o=TagObject(key,l.split('\t'),'exif')
            tag_objects[o.key]=o

    f=open("iptc-tags","r")
    data=f.read()
    lines=data.split('\n')
    key=lines.pop(0).split('\t')
    key='tag_hex,tag_dec,key,type,multiple,repeat,bytes_min,bytes_max,description'.split(',')
    for l in lines:
        if l:
            o=TagObject(key,l.split('\t'),'iptc')
            tag_objects[o.key]=o

    f=open("xmp-tags","r")
    data=f.read()
    schemas=data.split('prefix=')
    schemas.pop(0)
    for s in schemas:
        lines=s.split('\n')
        schema=lines.pop(0).strip()
        key=lines.pop(0).split('\t')
        key='property,label,value_type,type,category,description'.split(',')
        for l in lines:
            if l:
                o=TagObject_from_xmp_data(key,l.split('\t'),schema)
                tag_objects[o.key]=o

    print len(tag_objects),"tag objects read."

    return tag_objects

if __name__=='__main__':
    tag_defs=get_tag_info()

    print 'Metadata Viewer'
    fname=''
    if (len(sys.argv) > 1):
        fname=sys.argv[1]

    app = App(fname,tag_defs)
    app.run()


'''

    picty - Configuration Plugin
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


import gtk
import gobject
import os

from picty import settings
from picty import pluginbase
from picty import pluginmanager
from picty import baseobjects
from picty import collectionmanager

class ConfigPlugin(pluginbase.Plugin):
    name='ConfigPlugin'
    display_name='Preferences Dialog'
    api_version='0.1'
    version='0.4'
    def __init__(self):
        pass

    def plugin_init(self,mainframe,app_init):
        self.mainframe=mainframe
        self.config=None #defer creation until the dialog is requested (saves resources, faster startup)
#        self.mainframe.sidebar.append_page(self.config,gtk.Label("Configure"))

    def plugin_shutdown(self,app_shutdown):
        pass

    def app_config_dialog(self):
        if self.config==None:
            self.config=ConfigPanel(self)
        response=self.config.run()
        self.config.hide()
        return True


'''
Global settings can be found here
Plugins
* List of plugins (checkbox disable)
Custom shell tools
* Tool name
* Command line
* Mimetype/Infotype
Overlay information
* Title/Filename
* Exposure info
Per Collection settings are stored with the collection, includes:
* Refresh collection startup (checkbox)
* Refresh collection now (button)
* Caching options (number of thumbnails, number of images)
'''

class ConfigPanel(gtk.Dialog):
    def __init__(self,plugin):
        gtk.Dialog.__init__(self,flags=gtk.DIALOG_MODAL)
        self.plugin=plugin
        self.set_default_size(700,400)
        nb=gtk.Notebook()
        self.vbox.pack_start(nb)

        def page(nb,text,panel):
            page=gtk.ScrolledWindow()
            page.set_policy(gtk.POLICY_AUTOMATIC,gtk.POLICY_AUTOMATIC)
            page.add_with_viewport(panel)
            label=gtk.Label()
            label.set_markup('<b>'+text+'</b>')
            nb.append_page(page,label)
            return panel

        page(nb,"About",AboutBox())
        page(nb,"General",GeneralBox())
#        page(nb,"Collections",CollectionsBox(plugin))
        page(nb,"Plugins",PluginBox())
        page(nb,"Tools",ToolsBox())
        self.add_button("_Close",gtk.RESPONSE_ACCEPT)
        nb.show_all()
    def save_settings(self):
        pass
    def load_settings(self):
        pass

class ToolsBox(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)
        ##tool name, mimetype, command
        self.model=gtk.ListStore(gobject.TYPE_STRING,gobject.TYPE_STRING,gobject.TYPE_STRING)
        self.init_view()
        self.view=gtk.TreeView(self.model)
        self.pack_start(self.view)

        hbox=gtk.HBox()
        add_button = gtk.Button(stock=gtk.STOCK_ADD)
        add_button.connect('clicked', self.add_signal)
        delete_button = gtk.Button(stock=gtk.STOCK_REMOVE)
        delete_button.connect('clicked', self.delete_signal)
        hbox.pack_start(add_button,False)
        hbox.pack_start(delete_button,False)
        self.pack_start(hbox, False)

        name=gtk.CellRendererText()
        name.set_property("editable",True)
        #name.set_property('mode',gtk.CELL_RENDERER_MODE_EDITABLE) ##implicit in editable property?
        name.connect("edited",self.name_edited_signal)
        self.view.append_column(gtk.TreeViewColumn('Name',name,text=0))
        mime=gtk.CellRendererText()
        mime.set_property("editable",True)
        mime.connect("edited",self.mime_edited_signal)
        self.view.append_column(gtk.TreeViewColumn('Mimetype',mime,text=1))
        command=gtk.CellRendererText()
        command.set_property("editable",True)
        command.connect("edited",self.command_edited_signal)
        self.view.append_column(gtk.TreeViewColumn('Command',command,text=2))
        self.default_name='New Command'

    def init_view(self):
        self.model.clear()
        for mime,tools in settings.custom_launchers.iteritems():
            for tool in tools:
                self.model.append((tool[0],mime,tool[1]))

    def name_edited_signal(self, cellrenderertext, path, new_text):
        name,mime,cmd=self.model[path]
        if new_text==self.default_name:
            return
        if name==self.default_name:
            if mime in settings.custom_launchers:
                settings.custom_launchers[mime].append((new_text,cmd))
            else:
                settings.custom_launchers[mime]=[(new_text,cmd)]
            self.model[path][0]=new_text
            return
        for i in range(len(settings.custom_launchers[mime])):
            n,c=settings.custom_launchers[mime][i]
            if n==name and c==cmd:
                settings.custom_launchers[mime][i]=(new_text,c)
                break
        self.model[path][0]=new_text

    def mime_edited_signal(self, cellrenderertext, path, new_text):
        name,mime,cmd=self.model[path]
        if name==self.default_name:
            self.model[path][1]=new_text
            return
        for i in range(len(settings.custom_launchers[mime])):
            n,c=settings.custom_launchers[mime][i]
            if n==name and c==cmd:
                del settings.custom_launchers[mime][i]
                if len(settings.custom_launchers[mime])==0:
                    del settings.custom_launchers[mime]
                break
        if new_text not in settings.custom_launchers:
            settings.custom_launchers[new_text]=[(n,c)]
        else:
            settings.custom_launchers[new_text].append((n,c))
        self.model[path][1]=new_text

    def command_edited_signal(self, cellrenderertext, path, new_text):
        name,mime,cmd=self.model[path]
        if name==self.default_name:
            self.model[path][2]=new_text
            return
        for i in range(len(settings.custom_launchers[mime])):
            n,c=settings.custom_launchers[mime][i]
            if n==name and c==cmd:
                settings.custom_launchers[mime][i]=(n,new_text)
                break
        self.model[path][2]=new_text

    def add_signal(self, widget):
        self.model.append((self.default_name,'default',''))

    def delete_signal(self, widget):
        sel=self.view.get_selection()
        if not sel:
            return
        model,iter=sel.get_selected()
        if iter==None:
            return
        name,mime,cmd=self.model[iter]
        if name==self.default_name:
            self.model.remove(iter)
            return
        for i in range(len(settings.custom_launchers[mime])):
            n,c=settings.custom_launchers[mime][i]
            if n==name and c==cmd:
                del settings.custom_launchers[mime][i]
                if len(settings.custom_launchers[mime])==0:
                    del settings.custom_launchers[mime]
                break
        self.model.remove(iter)

class GeneralBox(gtk.HBox):
    def __init__(self):
        gtk.HBox.__init__(self)
        a_frame=gtk.Frame("Overlay")
        b_frame=gtk.Frame("Drag and Drop")
        c_frame=gtk.Frame("Image Viewer")
        a_box=gtk.VBox()
        b_box=gtk.VBox()
        c_box=gtk.VBox()
        a_frame.add(a_box)
        b_frame.add(b_box)
        c_frame.add(c_box)
        def box_add_check(box,text,var_name,callback=None):
            button=gtk.CheckButton(text)
            button.set_active(settings.__dict__[var_name])
            if callback is not None:
                button.connect("toggled",callback,var_name)
            else:
                button.connect("toggled",self.toggle_check,var_name)
            box.pack_start(button,False)
            return button
        box_add_check(a_box,'Show title','overlay_show_title')
        box_add_check(a_box,'Show path','overlay_show_path')
        box_add_check(a_box,'Show tags','overlay_show_tags')
        box_add_check(a_box,'Show date and time','overlay_show_date')
        box_add_check(a_box,'Show exposure details','overlay_show_exposure')
        box_add_check(b_box,'Apply image edits','dragdrop_apply_edits')
        box_add_check(b_box,'Strip image metadata','dragdrop_strip_metadata')
        box_add_check(b_box,'Resize image','dragdrop_resize',self.toggle_size)
        box_add_check(c_box,'Use fullscreen view only','viewer_fullscreen_only')
        box_add_check(c_box,'Use other monitor if present','viewer_other_monitor')
        size_box = gtk.HBox()
        size_box.pack_start(gtk.Label('Maximum length (pixels)'))
        self.size_entry = gtk.Entry()
        self.size_entry.set_max_length(5)
        self.size_entry.set_sensitive(settings.dragdrop_resize)
        self.size_entry.set_text(str(settings.dragdrop_max_size))
        self.size_entry.connect('changed',self.size_changed,'dragdrop_max_size')
        size_box.pack_start(self.size_entry)
        b_box.pack_start(size_box,False)
#        self.pack_start(b_box,False)
        self.pack_start(a_frame,False)
#        self.pack_start(c_box,False)
        self.pack_start(b_frame,False)
        self.pack_start(c_frame,False)
        self.show_all()

    def toggle_check(self,widget,var_name):
        settings.__dict__[var_name]=widget.get_active()

    def toggle_size(self,widget,var_name):
        settings.__dict__[var_name]=widget.get_active()
        self.size_entry.set_sensitive(widget.get_active())

    def size_changed(self,entry,var_name):
        try:
            size=int(entry.get_text())
            if size>0:
                settings.__dict__[var_name] = size
            else:
                settings.__dict__[var_name]=0
        except:
            settings.__dict__[var_name]=0


class CollectionsBox(gtk.HBox):
    def __init__(self,plugin):
        gtk.HBox.__init__(self)
        ##tool name, mimetype, command
        self.plugin=plugin

        vbox_left=gtk.VBox()
        vbox_right=gtk.VBox()
        self.pack_start(vbox_left, False)
        self.pack_start(vbox_right)

        self.model=plugin.mainframe.coll_set.add_model('LOCALSTORE_SELECTOR')
        self.view=gtk.TreeView(self.model)
        name=gtk.CellRendererText()
        name.set_property("editable",True)
        self.view.append_column(gtk.TreeViewColumn('Collections',name,text=collectionmanager.COLUMN_NAME,weight=collectionmanager.COLUMN_FONT_WGT))
        vbox_left.pack_start(self.view,True)

        hbox=gtk.ButtonBox()
        add_button = gtk.Button(stock=gtk.STOCK_ADD)
        add_button.connect('clicked', self.add_signal)
        delete_button = gtk.Button(stock=gtk.STOCK_REMOVE)
        delete_button.connect('clicked', self.delete_signal)
        hbox.pack_start(add_button,False)
        hbox.pack_start(delete_button,False)
#        vbox_left.pack_start(hbox,False)

    def add_signal(self, widget):
        name=self.plugin.mainframe.entry_dialog('New Collection','Name:')
        if not name:
            return
        coll_dir=settings.user_add_dir()
        if len(coll_dir)>0:
            if baseobjects.create_empty_file(name,coll_dir):
                self.model.append((name,400))

    def delete_signal(self, widget):
        sel=self.view.get_selection()
        model,iter=sel.get_selected()
        if iter==None:
            return
        name=self.model[iter][0]
        if name==settings.active_collection:
            return
        try:
            os.remove(os.path.join(settings.collections_dir,name))
        except:
            return
        self.model.remove(iter)



#    def name_edited_signal(self, cellrenderertext, path, new_text):
#        return
#        name=self.model[path]
#        if new_text==self.default_name:
#            return
#        if name==self.default_name:
#            if mime in settings.custom_launchers:
#                settings.custom_launchers[mime].append((new_text,cmd))
#            else:
#                settings.custom_launchers[mime]=[(new_text,cmd)]
#            self.model[path][0]=new_text
#            return
#        for i in range(len(settings.custom_launchers[mime])):
#            n,c=settings.custom_launchers[mime][i]
#            if n==name and c==cmd:
#                settings.custom_launchers[mime][i]=(new_text,c)
#                break
#        self.model[path][0]=new_text
#
#


class PluginBox(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)
        ##plugin name, plugin long name, version, enabled, can be disabled
        self.model=gtk.ListStore(gobject.TYPE_STRING,gobject.TYPE_STRING,gobject.TYPE_STRING,gobject.TYPE_BOOLEAN,gobject.TYPE_BOOLEAN)
        self.get_plugins()
        view=gtk.TreeView(self.model)
        self.pack_start(view)
        name=gtk.CellRendererText()
        view.append_column(gtk.TreeViewColumn('Name',name,text=1))
        version=gtk.CellRendererText()
        view.append_column(gtk.TreeViewColumn('Version',version,text=2))
        enable_toggle=gtk.CellRendererToggle()
        enable_toggle.connect('toggled',self.enable_toggle_signal)
        view.append_column(gtk.TreeViewColumn('Enabled',enable_toggle,active=3,activatable=4))

    def get_plugins(self):
        self.model.clear()
        for p,v in pluginmanager.mgr.plugins.iteritems():
            self.model.append((v[1].name,v[1].display_name,v[1].version,p not in settings.plugins_disabled,v[1]!=ConfigPlugin))

    def enable_toggle_signal(self,widget,path):
        plugin=self.model[path][0]
        if plugin in settings.plugins_disabled:
            del settings.plugins_disabled[settings.plugins_disabled.index(plugin)]
            pluginmanager.mgr.enable_plugin(plugin)
#            pluginmanager.mgr.callback_plugin(plugin,'plugin_init',pluginmanager.mgr.mainframe,False)
            self.model[path][3]=True
        else:
            settings.plugins_disabled.append(plugin)
            pluginmanager.mgr.disable_plugin(plugin)
            self.model[path][3]=False

class AboutBox(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self,False,10)
        pb=gtk.gdk.pixbuf_new_from_file(settings.splash_file)
        pb=pb.scale_simple(128,128,gtk.gdk.INTERP_BILINEAR)
        icon=gtk.image_new_from_pixbuf(pb)
        picty=gtk.Label()
        picty.set_markup('<b><big>picty</big></b>')
        version=gtk.Label('Version '+settings.release_version)
        author=gtk.Label('(C) Damien Moore 2013')
        contributors=gtk.Label('Contributors: antistress, yeKcim, Stuart Tilley')
        help=gtk.Button('Get Help')
        help.connect('clicked',self.browser_open,'http://groups.google.com/group/picty')
        project=gtk.Button('Project Page')
        project.connect('clicked',self.browser_open,'https://launchpad.net/picty')
        bug=gtk.Button('Report a bug')
        bug.connect('clicked',self.browser_open,'https://bugs.launchpad.net/picty/+filebug')
        bb=gtk.HButtonBox()
        bl=gtk.HBox()
        br=gtk.HBox()
        hb=gtk.HBox()
        hb.pack_start(bl,True)
        hb.pack_start(bb,False)
        hb.pack_start(br,True)
        bb.pack_start(help,False,False,20)
        bb.pack_start(project,False,False,20)
        bb.pack_start(bug,False,False,20)
        self.pack_start(icon,False,False,10)
        widgets=(picty,version,author,contributors)
        for w in widgets:
            self.pack_start(w,False)
        self.pack_end(hb,False,False,10)
    def browser_open(self,widget,url):
        import webbrowser
        webbrowser.open(url)

'''

    phraymd
    Copyright (C) 2009  Damien Moore

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

##standard imports
import os
import os.path
import threading
import gobject

##phraymd imports
import settings

## contains a list of errors
## each error is a tuple (optype,imagepath,[destpath])
fileoperrors=[]

##todo: list of items could be the selection in a view/collection (so check selected bit before copy)


class Worker:
    def __init__(self):
        self.active=False
        self.kill=False

    def _delete(self):
        trashdir=os.path.join(settings.active_collection.image_dirs[0],'.trash')
        for i in range(len(self.items)):
            item=self.items[i]
            if self.kill:
                self.active=False
                return
            if self.cb:
                gobject.idle_add(self.cb,None,1.0*i/len(self.items),'Deleting '+item.filename)
            try:
                empty,imdir,relpath=item.filename.partition(settings.active_collection.image_dirs[0])
                relpath=relpath.strip('/')
                if relpath:
                    dest=os.path.join(trashdir,relpath)
                    if os.path.exists(dest):
                        os.remove(dest)
                    os.renames(item.filename,dest)
            except:
                fileoperrors.append(('del',item))
        if self.cb:
            gobject.idle_add(self.cb,None,2.0,'Finished Deleting')
        self.active=False

    def delete(self,items,cb,selected_only=True):
        if self.active:
            return False
        self.active=True
        self.kill=False
        if selected_only:
            self.items=[]
            for i in range(len(items)):
                item=items(i)
                if item.selected:
                    self.items.append(item)
        else:
            self.items=items
        self.cb=cb
        self.thread=threading.Thread(target=self._delete)
        self.thread.start()
        return True

    def _copy(self):
        for i in range(len(self.items)):
            item=self.items[i]
            if self.kill:
                self.active=False
                return
            if self.cb:
                gobject.idle_add(self.cb,None,1.0*i/len(self.items),'Copying '+item.filename)
            try:
                fin=open(item.filename,'rb')
                fout=open(os.path.join(self.destdir,os.path.split(item.filename)[1]),'wb') ##todo: check exists (and what about perms/attribs?)
                fout.write(fin.read())
            except:
                fileoperrors.append(('copy',item,self.destdir))
        if self.cb:
            gobject.idle_add(self.cb,None,2.0,'Finished Copying')
        self.active=False

    def copy(self,items,destdir,cb,selected_only=True):
        if self.active:
            return False
        self.active=True
        self.kill=False
        if selected_only:
            self.items=[]
            for i in range(len(items)):
                item=items(i)
                if item.selected:
                    self.items.append(item)
        else:
            self.items=items
        self.cb=cb
        self.destdir=destdir
        self.thread=threading.Thread(target=self._copy)
        self.thread.start()
        return True

    def _move(self):
        for i in range(len(self.items)):
            item=self.items[i]
            if self.kill:
                self.active=False
                return
            if self.cb:
                gobject.idle_add(self.cb,None,1.0*i/len(self.items),'Moving '+item.filename)
            try:
                os.renames(item.filename,os.path.join(self.destdir,os.path.split(item.filename)[1]))
            except:
                fileoperrors.append(('move',item,self.destdir))
        if self.cb:
            gobject.idle_add(self.cb,None,2.0,'Finished Moving')
        self.active=False

    def move(self,items,destdir,cb,selected_only=True):
        if self.active:
            return False
        self.active=True
        self.kill=False
        if selected_only:
            self.items=[]
            for i in range(len(items)):
                item=items(i)
                if item.selected:
                    self.items.append(items(i))
        else:
            self.items=items
        self.cb=cb
        self.destdir=destdir
        self.thread=threading.Thread(target=self._move)
        self.thread.start()
        return True

    def kill_op(self):
        self.kill=True

    def is_active(self):
        return self.active

worker=Worker()

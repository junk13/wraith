#!/usr/bin/env python
""" wraith-rt.py - defines the wraith gui

 TODO:
  1) make tkMessageBox,tkFileDialog and tkSimpleDialog derive match
    main color scheme
  3) should we add a Database submenu for options like fix database?
  4) move display of log panel to after intializiation() so that
     wraith panel is 'first', leftmost panel - will have to figure out
     how to save messages from init to later
  8) need to periodically check status of postgres,nidusd and dyskt
  9) get log panel to scroll automatically
 10) add labels to frames
 11) break down starting storage components seperately: 1) start postgresql, 2) start
    nidus, 3) connect to postgress
"""

__name__ = 'wraith-rt'
__license__ = 'GPL v3.0'
__version__ = '0.0.3'
__revdate__ = 'February 2015'
__author__ = 'Dale Patterson'
__maintainer__ = 'Dale Patterson'
__email__ = 'wraith.wireless@yandex.com'
__status__ = 'Development'

import time                        # sleeping
import psycopg2 as psql            # postgresql api
import Tix                         # Tix gui stuff
import tkMessageBox as tkMB        # info dialogs
from PIL import Image,ImageTk      # image input & support
import ConfigParser                # config file parsing
import wraith                      # helpful functions/version etc
import wraith.widgets.panel as gui # graphics suite
from wraith.utils import bits      # bitmask functions
from wraith.utils import cmdline   # command line stuff

#### CONSTANTS

_BINS_ = "ABCDEFG"                     # data bin ids
NIDUSLOG = '/var/log/wraith/nidus.log' # path to nidus log
DYSKTLOG = '/var/log/wraith/dyskt.log' # path to dyskt log
NIDUSPID = '/var/run/nidusd.pid'       # path to nidus pidfile
DYSKTPID = '/var/run/dysktd.pid'       # path to dyskt pidfile

##### THE GUI(s)

class DataBinPanel(gui.SimplePanel):
    """ DataBinPanel - displays a set of data bins for retrieved data storage """
    def __init__(self,toplevel,chief):
        gui.SimplePanel.__init__(self,toplevel,chief,"Databin","widgets/icons/databin.png")

    def donothing(self): pass

    def _body(self):
        """ creates the body """
        self._bins = {}
        frm = Tix.Frame(self)
        frm.pack(side=Tix.TOP,expand=False)

        # add the bin buttons

        for b in _BINS_:
            try:
                self._bins[b] = {'img':ImageTk.PhotoImage(Image.open('widgets/icons/bin%s.png'%b))}
            except:
                self._bins[b] = {'img':None}
                self._bins[b]['btn'] = Tix.Button(frm,text=b,command=self.donothing)
            else:
                self._bins[b]['btn'] = Tix.Button(frm,image=self._bins[b]['img'],command=self.donothing)
            self._bins[b]['btn'].grid(row=0,column=_BINS_.index(b),sticky=Tix.W)

class AboutPanel(gui.SimplePanel):
    """ AboutPanel - displays a simple About Panel """
    def __init__(self,toplevel,chief):
        gui.SimplePanel.__init__(self,toplevel,chief,"About Wraith","widgets/icons/about.png")

    def _body(self):
        frm = Tix.Frame(self)
        frm.pack(side=Tix.TOP,fill=Tix.BOTH,expand=True)
        self.logo = ImageTk.PhotoImage(Image.open("widgets/icons/wraith-banner.png"))
        Tix.Label(frm,bg="white",image=self.logo).grid(row=0,column=0,sticky=Tix.N)
        Tix.Label(frm,
                  text="wraith-rt %s" % wraith.__version__,
                  fg="white",
                  font=("Roman",16,'bold')).grid(row=1,column=0,sticky=Tix.N)
        Tix.Label(frm,
                  text="Wireless assault, reconnaissance, collection and exploitation toolkit",
                  fg="white",
                  font=("Roman",8,'bold')).grid(row=2,column=0,sticky=Tix.N)

#class WraithConfigPanel(SimplePanel):
#    """ Display Wraith Configuration Panel """
#    def __init__(self,toplevel,chief):
#        SimplePanel.__init__(self,toplevel,chief,"Configure Wraith","widgets/icons/config.png")
#
#    def _body(self):
#        """ make wigets for the body """
#        # main frame
#        frm = Tix.Frame(self)
#        frm.pack(side=Tix.TOP,fill=Tix.BOTH,expand=True)

        # Two subframes, Storage and Policy
#        frmS = Tix.LabelFrame(frm)
#        frmS.grid(row=0,column=0,sticky=Tix.N)

#        frmP = Tix.LabelFrame(frm)
#        frmP.grid(row=1,column=0,sticky=Tix.N)

#### STATE DEFINITIONS
_STATE_INIT_   = 0
_STATE_STORE_  = 1
_STATE_CONN_   = 2
_STATE_NIDUS_  = 3
_STATE_DYSKT_  = 4
_STATE_EXIT_   = 5
_STATE_FLAGS_NAME_ = ['init','store','conn','nidus','dyskt','exit']
_STATE_FLAGS_ = {'init':(1 << 0),   # initialized properly
                 'store':(1 << 1),  # storage instance is running (i.e. postgresql)
                 'conn':(1 << 2),   # connected to storage instance
                 'nidus':(1 << 3),  # nidus storage manager running
                 'dyskt':(1 << 4),  # at least one sensor is collecting data
                 'exit':(1 << 5)}   # exiting/shutting down

class WraithPanel(gui.MasterPanel):
    """ WraithPanel - master panel for wraith gui """
    def __init__(self,toplevel):
        # set up, initialize parent and then initialize the gui
        # our variables
        self._conf = None  # configuration
        self._state = 0    # bitmask state
        self._conn = None  # connection to data storage
        self._bSQL = False # postgresql was running on startup
        self._pwd = None   # sudo password (should we not save it?)

        # set up super
        gui.MasterPanel.__init__(self,toplevel,"Wraith  v%s" % wraith.__version__,
                                 [],True,"widgets/icons/wraith2.png")

#### PROPS

    @property
    def getstate(self): return self._state

    @property
    def getstateflags(self): return bits.bitmask_list(_STATE_FLAGS_,self._state)

#### OVERRIDES

    def _initialize(self):
        """ initialize gui, determine initial state """
        # configure panel & write initial message
        # have to manually enter the desired size, as the menu does not expand
        # the visibile portion automatically
        self.tk.wm_geometry("300x1+0+0")
        self.tk.resizable(0,0)
        self.logwrite("Wraith v%s" % wraith.__version__)

        # read in conf file, exit on error
        confMsg = self._readconf()
        if confMsg:
            self.logwrite(confMsg,gui.LOG_ERR)
            return

        # determine if postgresql is running
        if cmdline.runningprocess('postgres'):
            self._bSQL = True

            # update state
            self._setstate(_STATE_STORE_)

            curs = None
            try:
                # attempt to connect and set state accordingly
                self._conn = psql.connect(host=self._conf['store']['host'],
                                          dbname=self._conf['store']['db'],
                                          user=self._conf['store']['user'],
                                          password=self._conf['store']['pwd'],)

                # set to use UTC and enable CONN flag
                curs = self._conn.cursor()
                curs.execute("set time zone 'UTC';")
                self._conn.commit()

                self.logwrite("Connected to database")
                self._setstate(_STATE_CONN_)
            except psql.OperationalError as e:
                if e.__str__().find('connect') > 0:
                    self.logwrite("PostgreSQL is not running",gui.LOG_WARN)
                    self._setstate(_STATE_STORE_,False)
                elif e.__str__().find('authentication') > 0:
                    self.logwrite("Authentication string is invalid",gui.LOG_ERR)
                else:
                    self.logwrite("Unspecified DB error occurred",gui.LOG_ERR)
                    self._conn.rollback()
            finally:
                if curs: curs.close()
        else:
            self.logwrite("PostgreSQL is not running",gui.LOG_WARN)

                # nidus running?
        if cmdline.nidusrunning(NIDUSPID):
            self.logwrite("Nidus is running")
            self._setstate(_STATE_NIDUS_)
        else:
            self.logwrite("Nidus is not running",gui.LOG_WARN)

        if cmdline.dysktrunning(DYSKTPID):
            self.logwrite("DySKT is running")
            self._setstate(_STATE_DYSKT_)
        else:
            self.logwrite("DySKT is not running",gui.LOG_WARN)

        # set initial state to initialized
        self._setstate(_STATE_INIT_)

        # adjust menu options accordingly
        self._menuenable()

    def _shutdown(self):
        """ if connected to datastorage, closes connection """
        # set the state
        self._setstate(_STATE_EXIT_)

        # shutdown dyskt
        self._stopsensor()

        # shutdown storage
        self._stopstorage()

    def _makemenu(self):
        """ make the menu """
        self.menubar = Tix.Menu(self)

        # File Menu
        # all options will always be enabled
        self.mnuWraith = Tix.Menu(self.menubar,tearoff=0)
        self.mnuWraithGui = Tix.Menu(self.mnuWraith,tearoff=0)
        self.mnuWraithGui.add_command(label='Save',command=self.guisave)
        self.mnuWraithGui.add_command(label='Load',command=self.guiload)
        self.mnuWraith.add_cascade(label='Gui',menu=self.mnuWraithGui)
        self.mnuWraith.add_separator()
        self.mnuWraith.add_command(label='Configure',command=self.configwraith)
        self.mnuWraith.add_separator()
        self.mnuWraith.add_command(label='Exit',command=self.panelquit)

        # Tools Menu
        # all options will always be enabled
        self.mnuTools = Tix.Menu(self.menubar,tearoff=0)
        self.mnuToolsCalcs = Tix.Menu(self.mnuTools,tearoff=0)
        self.mnuTools.add_cascade(label="Calcuators",menu=self.mnuToolsCalcs)

        # View Menu
        # all options will always be enabled
        self.mnuView = Tix.Menu(self.menubar,tearoff=0)
        self.mnuView.add_command(label='Data Bins',command=self.viewdatabins)
        self.mnuView.add_separator()
        self.mnuView.add_command(label='Data',command=self.viewdata)

        # Storage Menu
        self.mnuStorage = Tix.Menu(self.menubar,tearoff=0)
        self.mnuStorage.add_command(label="Start All",command=self.storagestart)  # 0
        self.mnuStorage.add_command(label="Stop All",command=self.storagestop)    # 1
        self.mnuStorage.add_separator()                                           # 2
        self.mnuStoragePSQL = Tix.Menu(self.mnuStorage,tearoff=0)
        self.mnuStoragePSQL.add_command(label='Start',command=self.psqlstart)       # 0
        self.mnuStoragePSQL.add_command(label='Stop',command=self.psqlstop)         # 1
        self.mnuStoragePSQL.add_separator()                                         # 2
        self.mnuStoragePSQL.add_command(label='Connect',command=self.connect)       # 3
        self.mnuStoragePSQL.add_command(label='Disconnect',command=self.disconnect) # 4      # 1
        self.mnuStoragePSQL.add_separator()                                         # 5
        self.mnuStoragePSQL.add_command(label='Fix',command=self.psqlfix)           # 6
        self.mnuStoragePSQL.add_command(label='Delete All',command=self.psqldelall) # 7
        self.mnuStorage.add_cascade(label='PostgreSQL',menu=self.mnuStoragePSQL)  # 3
        self.mnuStorageNidus = Tix.Menu(self.mnuStorage,tearoff=0)
        self.mnuStorageNidus.add_command(label='Start',command=self.nidusstart)     # 0
        self.mnuStorageNidus.add_command(label='Stop',command=self.nidusstop)       # 1
        self.mnuStorageNidus.add_separator()                                        # 2
        self.mnuNidusLog = Tix.Menu(self.mnuStorageNidus,tearoff=0)
        self.mnuNidusLog.add_command(label='View',command=self.viewniduslog)         # 0
        self.mnuNidusLog.add_command(label='Clear',command=self.clearniduslog)       # 1
        self.mnuStorageNidus.add_cascade(label='Log',menu=self.mnuNidusLog)         # 3
        self.mnuStorageNidus.add_separator()                                        # 4
        self.mnuStorageNidus.add_command(label='Config',command=self.confignidus)   # 5
        self.mnuStorage.add_cascade(label='Nidus',menu=self.mnuStorageNidus)      # 4

        # DySKT Menu
        self.mnuDySKT = Tix.Menu(self.menubar,tearoff=0)
        self.mnuDySKT.add_command(label='Start',command=self.dysktstart)   # 0
        self.mnuDySKT.add_command(label='Stop',command=self.dysktstop)     # 1
        self.mnuDySKT.add_separator()                                      # 2
        self.mnuDySKT.add_command(label='Control',command=self.dysktctrl)  # 3            # 3
        self.mnuDySKT.add_separator()                                      # 4
        self.mnuDySKTLog = Tix.Menu(self.mnuDySKT,tearoff=0)
        self.mnuDySKTLog.add_command(label='View',command=self.viewdysktlog)   # 0
        self.mnuDySKTLog.add_command(label='Clear',command=self.cleardysktlog) # 1
        self.mnuDySKT.add_cascade(label='Log',menu=self.mnuNidusLog)       # 5
        self.mnuDySKT.add_separator()                                      # 6
        self.mnuDySKT.add_command(label='Config',command=self.configdyskt) # 7

        # Help Menu
        self.mnuHelp = Tix.Menu(self.menubar,tearoff=0)
        self.mnuHelp.add_command(label='About',command=self.about)
        self.mnuHelp.add_command(label='Help',command=self.help)

        # add the menus
        self.menubar.add_cascade(label='Wraith',menu=self.mnuWraith)
        self.menubar.add_cascade(label="Tools",menu=self.mnuTools)
        self.menubar.add_cascade(label='View',menu=self.mnuView)
        self.menubar.add_cascade(label='Storage',menu=self.mnuStorage)
        self.menubar.add_cascade(label='DySKT',menu=self.mnuDySKT)
        self.menubar.add_cascade(label='Help',menu=self.mnuHelp)

#### MENU CALLBACKS

#### Wraith Menu
    def configwraith(self):
        """ display config file preference editor """
        panel = self.getpanels("preferences",False)
        #if not panel:
        #    t = Tix.Toplevel()
        #    pnl = WraithConfigPanel(t,self)
        #    self.addpanel(pnl._name,gui.PanelRecord(t,pnl,"preferences"))
        #else:
        #    panel[0].tk.deiconify()
        #    panel[0].tk.lift()

#### View Menu

    def viewdatabins(self):
        """ display the data bins panel """
        panel = self.getpanels("databin",False)
        if not panel:
            t = Tix.Toplevel()
            pnl = DataBinPanel(t,self)
            self.addpanel(pnl._name,gui.PanelRecord(t,pnl,"databin"))
        else:
            panel[0].tk.deiconify()
            panel[0].tk.lift()

    def viewdata(self):
        """ display data panel """
        self.unimplemented()

#### Storage Menu

    def storagestart(self):
        """ starts database and storage manager """
        self._startstorage()
        self._updatestate()
        self._menuenable()

    def storagestop(self):
        """ stops database and storage manager """
        self._stopstorage()
        self._updatestate()
        self._menuenable()

    def connect(self):
        """ connects to postgresql """
        pass

    def disconnect(self):
        """ connects to postgresql """
        pass

    def psqlstart(self):
        """ starts postgresql """
        pass

    def psqlstop(self):
        """ starts postgresql """
        pass

    def psqlfix(self):
        """ fix any open-ended periods left over by errors """
        pass

    def psqldelall(self):
        """ delete all data in nidus database """
        pass

    def nidusstart(self):
        """ starts nidus storage manager """
        pass

    def nidusstop(self):
        """ stops nidus storage manager """
        pass

    def viewniduslog(self):
        """ display Nidus log """
        self.unimplemented()

    def clearniduslog(self):
        """ clear nidus log """
        self.unimplemented()

    def confignidus(self):
        """ display nidus config file preference editor """
        self.unimplemented()

#### DySKT Menu

    def dysktstart(self):
        """ starts DySKT sensor """
        self._startsensor()
        self._updatestate()
        self._menuenable()

    def dysktstop(self):
        """ stops DySKT sensor """
        self._stopsensor()
        self._updatestate()
        self._menuenable()

    def dysktctrl(self):
        """ displays DySKT Control Panel """
        self.unimplemented()

    def viewdysktlog(self):
        """ display DySKT log """
        self.unimplemented()

    def cleardysktlog(self):
        """ clears the DySKT log """
        self.unimplemented()

    def configdyskt(self):
        """ display dyskt config file preference editor """
        self.unimplemented()

#### HELP MENU

    def about(self):
        """ display the about panel """
        panel = self.getpanels("about",False)
        if not panel:
            t = Tix.Toplevel()
            pnl = AboutPanel(t,self)
            self.addpanel(pnl._name,gui.PanelRecord(t,pnl,"about"))
        else:
            panel[0].tk.deiconify()
            panel[0].tk.lift()

    def help(self):
        """ display the help panel """
        self.unimplemented()

#### MINION METHODS

    def showpanel(self,desc):
        """ opens a panel of type desc """
        if desc == 'log': self.viewlog()
        elif desc == 'databin': self.viewdatabins()
        else: raise RuntimeError, "WTF Cannot open %s" % desc

#### HELPER FUNCTIONS

    def _updatestate(self):
        """ reevaluates internal state """
        # state of nidus
        if cmdline.nidusrunning(NIDUSPID): self._setstate(_STATE_NIDUS_)
        else: self._setstate(_STATE_NIDUS_,False)

        # state of dyskt
        if cmdline.dysktrunning(DYSKTPID): self._setstate(_STATE_DYSKT_)
        else:  self._setstate(_STATE_DYSKT_,False)

        # state of postgres i.e. store
        if cmdline.runningprocess('postgres'): self._setstate(_STATE_STORE_)
        else: self._setstate(_STATE_STORE_,False)

        # state of our connection - should figure out a way to determine if
        # connection is still 'alive'
        if self._conn: self._setstate(_STATE_CONN_)
        else: self._setstate(_STATE_CONN_,False)

    def _setstate(self,f,up=True):
        """ sets internal state's flag f to 1 if up is True or 0 otherwise """
        if up:
            self._state = bits.bitmask_set(_STATE_FLAGS_,
                                           self._state,
                                           _STATE_FLAGS_NAME_[f])
        else:
            self._state = bits.bitmask_unset(_STATE_FLAGS_,
                                             self._state,
                                             _STATE_FLAGS_NAME_[f])

    def _readconf(self):
        """ read in configuration file """
        conf = ConfigParser.RawConfigParser()
        if not conf.read("wraith.conf"): return "wraith.conf does not exist"

        self._conf = {}
        try:
            ## STORAGE
            self._conf['store'] = {'host':conf.get('Storage','host'),
                                   'db':conf.get('Storage','db'),
                                   'user':conf.get('Storage','user'),
                                   'pwd':conf.get('Storage','pwd')}

            ## POLICY
            self._conf['policy'] = {'polite':True,
                                   'shutdown':True}

            if conf.has_option('Policy','polite'):
                if conf.get('Policy','polite').lower() == 'off':
                    self._conf['policy']['polite'] = False
            if conf.has_option('Policy','shutdown'):
                if conf.get('Policy','shutdown').lower() == 'manual':
                    self._conf['ploicy']['shutdown'] = False

            # return no errors
            return ''
        except (ConfigParser.NoSectionError,ConfigParser.NoOptionError) as e:
            return e

    def _menuenable(self):
        """ enable/disable menus as necessary """
        # get all flags
        flags = bits.bitmask_list(_STATE_FLAGS_,self._state)

        # adjust storage menu
        # easiest for storage is to disable all and then only enable relevant
        # always allow Nidus->config, Nidus->View Log
        self.mnuStorage.entryconfig(0,state=Tix.DISABLED)      # all start
        self.mnuStorage.entryconfig(1,state=Tix.DISABLED)      # all stop
        self.mnuStoragePSQL.entryconfig(0,state=Tix.DISABLED)  # psql start
        self.mnuStoragePSQL.entryconfig(1,state=Tix.DISABLED)  # psql stop
        self.mnuStoragePSQL.entryconfig(3,state=Tix.DISABLED)  # connect 2 psql
        self.mnuStoragePSQL.entryconfig(4,state=Tix.DISABLED)  # disconnect from psql
        self.mnuStoragePSQL.entryconfig(6,state=Tix.DISABLED)  # psql fix
        self.mnuStoragePSQL.entryconfig(7,state=Tix.DISABLED)  # psql delete all
        self.mnuStorageNidus.entryconfig(0,state=Tix.DISABLED) # nidus start
        self.mnuStorageNidus.entryconfig(1,state=Tix.DISABLED) # nidus stop
        self.mnuNidusLog.entryconfig(1,state=Tix.DISABLED)     # nidus log clear

        if flags['store']:
            # storage is running enable stop all, stop postgresql, and start nidus
            self.mnuStorage.entryconfig(1,state=Tix.NORMAL)
            self.mnuStoragePSQL.entryconfig(1,state=Tix.NORMAL)
            self.mnuStorageNidus.entryconfig(0,state=Tix.NORMAL)
        else:
            # storage is not running, enable start all, start postgresql
            self.mnuStorage.entryconfig(0,state=Tix.NORMAL)
            self.mnuStoragePSQL.entryconfig(0,state=Tix.NORMAL)

        if flags['nidus']:
            # nidus is running, enable stop all, stop nidus
            self.mnuStorage.entryconfig(1,state=Tix.NORMAL)
            self.mnuStorageNidus.entryconfig(1,state=Tix.NORMAL)
        else:
            # nidus is not running, enable start all & clear nidus log
            # enable start nidus only if postgres is running
            self.mnuStorage.entryconfig(0,state=Tix.NORMAL)
            if flags['store']: self.mnuStorageNidus.entryconfig(0,state=Tix.NORMAL)
            self.mnuNidusLog.entryconfig(1,state=Tix.NORMAL)

        if flags['conn']:
            # connected to psql, enable stop all, disconnect
            self.mnuStorage.entryconfig(1,state=Tix.NORMAL)
            self.mnuStorage.entryconfig(4,state=Tix.NORMAL)
        else:
            # disconnected, enable start all, connect
            self.mnuStorage.entryconfig(0,state=Tix.NORMAL)
            self.mnuStorage.entryconfig(3,state=Tix.NORMAL)

        # adjust dyskt menu
        if not flags['store'] and not flags['nidus']:
            # cannot start/stop/control dyskt unless nidus & postgres is running
            self.mnuDySKT.entryconfig(0,state=Tix.DISABLED)  # start
            self.mnuDySKT.entryconfig(1,state=Tix.DISABLED)  # stop
            self.mnuDySKT.entryconfig(3,state=Tix.DISABLED)  # ctrl panel
            self.mnuDySKTLog.entryconfig(1,state=Tix.NORMAL) # clear log
            self.mnuDySKT.entryconfig(7,state=Tix.NORMAL)    # configure
        else:
            if flags['dyskt']:
                # DySKT sensor is running
                self.mnuDySKT.entryconfig(0,state=Tix.DISABLED)    # start
                self.mnuDySKT.entryconfig(1,state=Tix.NORMAL)      # stop
                self.mnuDySKT.entryconfig(3,state=Tix.NORMAL)      # ctrl panel
                self.mnuDySKTLog.entryconfig(1,state=Tix.DISABLED) # clear log
                self.mnuDySKT.entryconfig(7,state=Tix.NORMAL)      # configure
            else:
                # DySKT sensor is not running
                self.mnuDySKT.entryconfig(0,state=Tix.NORMAL)    # start
                self.mnuDySKT.entryconfig(1,state=Tix.DISABLED)  # stop
                self.mnuDySKT.entryconfig(3,state=Tix.DISABLED)  # ctrl panel
                #self.mnuDySKTLog.entryconfig(0,state=Tix.NORMAL) # view log
                self.mnuDySKTLog.entryconfig(1,state=Tix.NORMAL) # clear log
                self.mnuDySKT.entryconfig(7,state=Tix.NORMAL)    # configure

    def _startstorage(self):
        """ start postgresql db and nidus storage manager """
        # do we have a password
        if not self._pwd:
            pwd = self._getpwd()
            if pwd is None:
                self.logwrite("Password entry canceled. Cannot continue",gui.LOG_WARN)
                return
            self._pwd = pwd

        # get our flags
        flags = bits.bitmask_list(_STATE_FLAGS_,self._state)

        # start necessary storage components
        if not flags['store']:
            self.logwrite("Starting PostgreSQL...",gui.LOG_NOTE)
            try:
                # try sudo /etc/init.d/postgresql start
                cmdline.service('postgresql',self._pwd)
                time.sleep(0.5)
                if not cmdline.runningprocess('postgres'):
                    raise RuntimeError('unknown')
            except RuntimeError as e:
                self.logwrite("Error starting PostgreSQL: %s" % e,gui.LOG_ERR)
                return
            else:
                self.logwrite("PostgreSQL started")
                self._setstate(_STATE_STORE_)

        # start nidus
        if not flags['nidus']:
            self.logwrite("Starting Nidus...",gui.LOG_NOTE)
            try:
                cmdline.service('nidusd',self._pwd)
                time.sleep(0.5)
                if not cmdline.nidusrunning(NIDUSPID):
                    raise RuntimeError('unknown')
            except RuntimeError as e:
                self.logwrite("Error starting Nidus: %s" % e,gui.LOG_ERR)
            else:
                self.logwrite("Nidus Started")
                self._setstate(_STATE_NIDUS_)

        # connect to db
        self.logwrite("Connecting to Nidus Datastore...",gui.LOG_NOTE)
        curs = None
        try:
            # attempt to connect and set state accordingly
            self._conn = psql.connect(host=self._conf['store']['host'],
                                      dbname=self._conf['store']['db'],
                                      user=self._conf['store']['user'],
                                      password=self._conf['store']['pwd'],)

            # set to use UTC and enable CONN flag
            curs = self._conn.cursor()
            curs.execute("set time zone 'UTC';")
            self._conn.commit()

            self.logwrite("Connected to datastore")
            self._setstate(_STATE_CONN_)
        except psql.OperationalError as e:
            if e.__str__().find('connect') > 0:
                self.logwrite("PostgreSQL is not running",gui.LOG_WARN)
                self._setstate(_STATE_STORE_,False)
            elif e.__str__().find('authentication') > 0:
                self.logwrite("Authentication string is invalid",gui.LOG_ERR)
            else:
                self.logwrite("Unspecified DB error occurred",gui.LOG_ERR)
                self._conn.rollback()
        finally:
            if curs: curs.close()

    def _stopstorage(self):
        """ stop posgresql db and nidus storage manager """
        # get our flags
        flags = bits.bitmask_list(_STATE_FLAGS_,self._state)

        # if DySKT is running, prompt for clearance
        if flags['dyskt']:
            ans = tkMB.askquestion('DySKT Running',
                                   'Shutdown and lose queued data?',parent=self)
            if ans == 'no': return

        # return if no storage component is running
        if not (flags['store'] or flags['conn'] or flags['nidus']): return

        # do we have a password
        if not self._pwd:
            pwd = self._getpwd()
            if pwd is None:
                self.logwrite("Password entry canceled. Cannot continue",gui.LOG_WARN)
                return
            self._pwd = pwd

        # disconnect from db
        if self._conn:
            self.logwrite("Disconnecting from Nidus datastore",gui.LOG_NOTE)
            self._conn.close()
            self._conn = None
            self._setstate(_STATE_CONN_,False)
            self.logwrite("Disconnected from Nidus datastore")

        # before shutting down nidus & postgresql, confirm auto shutdown is enabled
        if not self._conf['policy']['shutdown']: return

        # shutdown nidus
        if flags['nidus']:
            try:
                self.logwrite("Shutting down Nidus",gui.LOG_NOTE)
                cmdline.service('nidusd',self._pwd,False)
                while cmdline.nidusrunning(NIDUSPID):
                    self.logwrite("Nidus still processing data...",gui.LOG_NOTE)
                    time.sleep(1.0)
            except RuntimeError as e:
                self.logwrite("Error shutting down Nidus: %s" % e,gui.LOG_ERR)
            else:
                self._setstate(_STATE_NIDUS_,False)
                self.logwrite("Nidus shut down")

        # shutdown postgresql (check first if polite)
        if self._conf['policy']['polite'] and self._bSQL: return

        if cmdline.runningprocess('postgres'):
            try:
                self.logwrite("Shutting down PostgreSQL",gui.LOG_NOTE)
                cmdline.service('postgresql',self._pwd,False)
                while cmdline.runningprocess('postgres'):
                    self.logwrite("PostgreSQL shutting down...",gui.LOG_NOTE)
                    time.sleep(1.0)
            except RuntimeError as e:
                self.logwrite("Error shutting down PostgreSQL",gui.LOG_ERR)
            else:
                self._setstate(_STATE_STORE_,False)
                self.logwrite("PostgreSQL shut down")

    def _startsensor(self):
        """ starts the DySKT sensor """
        pass

    def _stopsensor(self):
        """ stops the DySKT sensor """
        pass

    def _getpwd(self):
        """ prompts for sudo password until correct or canceled"""
        dlg = gui.PasswordDialog(self)
        try:
            # test out sudo pwd
            while not cmdline.testsudopwd(dlg.pwd):
                self.logwrite("Bad password entered. Try Again",gui.LOG_ERR)
                dlg = gui.PasswordDialog(self)
            return dlg.pwd
        except AttributeError:
            return None # canceled

if __name__ == 'wraith-rt':
    t = Tix.Tk()
    t.option_add('*foreground','blue')                # normal fg color
    t.option_add('*background','black')               # normal bg color
    t.option_add('*activeBackground','black')         # bg on mouseover
    t.option_add('*activeForeground','blue')          # fg on mouseover
    t.option_add('*disabledForeground','gray')        # fg on disabled widget
    t.option_add('*disabledBackground','black')       # bg on disabled widget
    t.option_add('*troughColor','black')              # trough on scales/scrollbars
    WraithPanel(t).mainloop()
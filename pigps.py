import pygame
import threading
import signal
import sys
import time
import fnmatch
import io
import os

from pygame.locals import *
from subprocess import call  
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.backends.backend_agg as agg
import pylab

try:
  import GpsController
except:
  pass
 
# GRAPH Setup
subplotpars=matplotlib.figure.SubplotParams(left=0.02, right=1.08, bottom=0.1, top=1.0, wspace=0.0, hspace=0.0)
fig = pylab.figure(figsize=[3.2, 1.2], # Inches
                   dpi=100,        # 100 dots per inch, so the resulting buffer is 320x120 pixels (half screen with this TFT)
                   facecolor='black',
                   subplotpars=subplotpars,
                   tight_layout=False)

# UI classes ---------------------------------------------------------------

# Icon is a very simple bitmap class, just associates a name and a pygame
# image (PNG loaded from icons directory) for each.
# There isn't a globally-declared fixed list of Icons.  Instead, the list
# is populated at runtime from the contents of the 'icons' directory.

class Icon:

    def __init__(self, name):
      self.name = name
      try:
        self.bitmap = pygame.image.load(iconPath + '/' + name + '.png')
      except:
        pass

# Button is a simple tappable screen region.  Each has:
#  - bounding rect ((X,Y,W,H) in pixels)
#  - optional background color and/or Icon (or None), always centered
#  - optional foreground Icon, always centered
#  - optional single callback function
#  - optional single value passed to callback
# Occasionally Buttons are used as a convenience for positioning Icons
# but the taps are ignored.  Stacking order is important; when Buttons
# overlap, lowest/first Button in list takes precedence when processing
# input, and highest/last Button is drawn atop prior Button(s).  This is
# used, for example, to center an Icon by creating a passive Button the
# width of the full screen, but with other buttons left or right that
# may take input precedence (e.g. the Effect labels & buttons).
# After Icons are loaded at runtime, a pass is made through the global
# buttons[] list to assign the Icon objects (from names) to each Button.

class Label:
  def __init__(self, rect, **kwargs):
    self.rect = rect
    self.font_size = 24
    self.color = (255,255,255)
    for key, value in kwargs.iteritems():
      if   key == 'font_size': self.font_size = value
      elif key == 'color': self.color = value
    # Set at runtime
    self.label_size = (0,0)

  def draw(self, screen, string, center=False):
    font = pygame.font.Font("fonts/OpenSans-Regular.ttf", self.font_size)
    font.set_bold(False)
    # New size of our label, based on new text
    new_label_size = font.size(string)
    # The rended object ready for drawing (blint)
    label = font.render(string, 1, self.color)
    # If centering, redraw over the old Rect, and store the new rect
    if center:
      # Get our screen just in case I update the display
      screen_width = screen.get_width()
      # Center via simple middle - width / 2
      new_x = (screen_width / 2) - (new_label_size[0] / 2)
      self.rect = (new_x, self.rect[1])
    # Erase our previous label with our saved size
    screen.fill(0, (self.rect, self.label_size))
    # Draw our new label
    screen.blit(label, self.rect)
    # Hang on to the new label's size so we can erase it.
    self.label_size = new_label_size
    # Return a Rect in case you want to be efficient and only update the proper rects 
    # As in pygame.display.update(rect|rect_list)
    return (self.rect, self.label_size)

class Button:

    def __init__(self, rect, **kwargs):
      self.rect     = rect # Bounds
      self.color    = None # Background fill color, if any
      self.iconBg   = None # Background Icon (atop color fill)
      self.iconFg   = None # Foreground Icon (atop background)
      self.bg       = None # Background Icon name
      self.fg       = None # Foreground Icon name
      self.callback = None # Callback function
      self.value    = None # Value passed to callback
      for key, value in kwargs.iteritems():
        if   key == 'color': self.color    = value
        elif key == 'bg'   : self.bg       = value
        elif key == 'fg'   : self.fg       = value
        elif key == 'cb'   : self.callback = value
        elif key == 'value': self.value    = value

    def selected(self, pos):
      x1 = self.rect[0]
      y1 = self.rect[1]
      x2 = x1 + self.rect[2] - 1
      y2 = y1 + self.rect[3] - 1
      if ((pos[0] >= x1) and (pos[0] <= x2) and
          (pos[1] >= y1) and (pos[1] <= y2)):
        if self.callback:
          if self.value is None: self.callback()
          else:                  self.callback(self.value)
        return True
      return False

    def draw(self, screen):
      if self.color:
        screen.fill(self.color, self.rect)
      if self.iconBg:
        screen.blit(self.iconBg.bitmap,
          (self.rect[0]+(self.rect[2]-self.iconBg.bitmap.get_width())/2,
           self.rect[1]+(self.rect[3]-self.iconBg.bitmap.get_height())/2))
      if self.iconFg:
        screen.blit(self.iconFg.bitmap,
          (self.rect[0]+(self.rect[2]-self.iconFg.bitmap.get_width())/2,
           self.rect[1]+(self.rect[3]-self.iconFg.bitmap.get_height())/2))

    def setBg(self, name):
      if name is None:
        self.iconBg = None
      else:
        for i in icons:
          if name == i.name:
            self.iconBg = i
            break

# Globals ---------------------------
should_listen = False
program_running = True
global screenMode
iconPath = 'img'
icons = []
plot_points = []
track_hash = '';

def set_screenMode(mode):
  global screenMode;
  screenMode = mode
def get_screenMode():
  global screenMode
  return screenMode

def erase_buttons_for_mode(mode):
  rects_to_draw = []
  for i,b in enumerate(buttons[mode]):
    screen.fill(0, b.rect)
    rects_to_draw.append(b.rect)
  pygame.display.update(rects_to_draw)

def draw_buttons_for_mode(mode):
  rects_to_draw = []
  for i,b in enumerate(buttons[mode]):
    print "Draw"
    b.draw(screen)
    rects_to_draw.append(b.rect)
  pygame.display.update(rects_to_draw)

def deal_with_screen_mode_and_buttons(n):
  erase_buttons_for_mode(get_screenMode())
  draw_buttons_for_mode(n)
  label_rect = labels["STATUS"].draw(screen, status_text[n])
  pygame.display.update(label_rect)
  set_screenMode(n)

# Lifecycle Methods ------------------
def start_track(n):
  # init gps
  # Start Event Listener
  # Create Hash For this Track
  # Change Button
  #gpsc.start()
  pygame.time.set_timer(USEREVENT+3, 15000)
  deal_with_screen_mode_and_buttons(n)

def pause_track(n):
  # Stop GPS (preserver battery)
  # Kill Event Listener
  #
  pygame.time.set_timer(USEREVENT+3, 0) 
  deal_with_screen_mode_and_buttons(n)

def finish_track(n):
  # Stop GPS
  # Close Track (set bool value on last db record)
  # Cleanup Graph/Display
  pygame.time.set_timer(USEREVENT+3, 0)
  deal_with_screen_mode_and_buttons(n)

def resume_last_track(n):
  # Start GPS
  # Start Event Listener
  # Get most recent, unfinished track
  # Go
  pygame.time.set_timer(USEREVENT+3, 15000)
  deal_with_screen_mode_and_buttons(n)

START = Button((225, 35, 85, 32), bg='start', cb=start_track, value=1)
PAUSE = Button((225, 35, 85, 32), bg='pause', cb=pause_track, value=2)
FINISH = Button((225, 74, 85, 32), bg='finish', cb=finish_track, value=0)
RESUME = Button((225, 74, 85, 32), bg='resume', cb=resume_last_track, value=1)

buttons = [
    # Screen mode 0 is main view screen of current status
    [
      START, # Initial Mode. Start Button
    ],
    [
      PAUSE, # Running Mode. Pause/Finish Buttons
      FINISH,
    ],
    [
      START, # Running but Paused Mode. Start/Finish Buttons
      FINISH, 
    ],
    [
      START, # Usually starting from powerdown and if a track has not been closed.
      RESUME
    ]
]

status_text = [
  "Waiting",
  "Running",
  "Paused",
]

labels = {
  "SPEED": Label((10,20), font_size=36, color=(255,255,255)),
  "TIME": Label((160,2), font_size=16, color=(255,255,255)),
  "STATUS": Label((225,17), font_size=12, color=(255,255,255)),
}

# Signal Handler
def signal_handler(signal, frame):
    print 'got SIGTERM'
    pygame.quit()
    sys.exit()

print "Setting fullscreen..."
try:
  #modes = pygame.display.list_modes(16)
  #screen = pygame.display.set_mode(modes[0], FULLSCREEN, 16)
  # Tell the RPi to use the TFT screen and that it's a touchscreen device
  #os.putenv('SDL_VIDEODRIVER', 'fbcon')
  #os.putenv('SDL_FBDEV'      , '/dev/fb1')
  #os.putenv('SDL_MOUSEDRV'   , 'TSLIB')
  #os.putenv('SDL_MOUSEDEV'   , '/dev/input/touchscreen')
  os.putenv('SDL_FBDEV', '/dev/fb1')
  os.putenv('SDL_MOUSEDRV', 'TSLIB')
  os.putenv('SDL_MOUSEDEV', '/dev/input/touchscreen')
  print "Initing Pygame Proper"
  pygame.init()
  #screen = pygame.display.set_mode((320, 240), pygame.NOFRAME)
  modes = pygame.display.list_modes(16)
  screen = pygame.display.set_mode(modes[0], FULLSCREEN, 16)
  print "TRY WORKED"
except Exception, e:
  print e
  print "Initing Pygame"
  pygame.init()
  screen = pygame.display.set_mode((320, 240), pygame.NOFRAME)
  print "TRY DIDNOT WORK"

print "Setting Mouse invisible..."
pygame.mouse.set_visible(False)
# Setup the DB
import sqlite3
conn = sqlite3.connect('db/pidb.db')
print conn
c = conn.cursor()
try:
  c.execute('SELECT * FROM gps ORDER BY price')
except Exception, e:
  c.execute('''CREATE TABLE IF NOT EXISTS gps
             (pk integer primary key, hash text, gps_date datetime, latitude real, longitude real, speed real, elevation real, complete_track integer)''')

screen.fill(0)
pygame.display.update()

# Arbitrary startup sleep
time.sleep(2)    

# Kill handler
signal.signal(signal.SIGTERM, signal_handler)

# Clock Updater
pygame.time.set_timer(USEREVENT+1, 1000)

# Graph Updater (Will eventually just update when GPS is updated)
pygame.time.set_timer(USEREVENT+2, 15000)

# Init Screen Mode
set_screenMode(0)

# Main Loop ---------------------------
print "mainloop.."
# gpsc = GpsController.GpsController()
# gpsc.start()
session = gps.gps()
session.stream(gps.WATCH_ENABLE | gps.WATCH_NEWSTYLE)
session.next()
# pygame.time.set_timer(USEREVENT+3, 15000)

while(program_running):
  # Once setup with screen modes, only do certain drawing methods when the screen mode changes.
  labels["SPEED"].draw(screen, "0 mph")
  labels["TIME"].draw(screen, time.strftime("%I:%M"), center=True)
  pygame.display.update()

  # Button Setup
  print "Loading Icons..."
  # Load all icons at startup.
  for file in os.listdir(iconPath):
    if fnmatch.fnmatch(file, '*.png'):
      icons.append(Icon(file.split('.')[0]))
  # Assign Icons to Buttons, now that they're loaded
  print"Assigning Buttons"
  for s in buttons:        # For each screenful of buttons...
    for b in s:            #  For each button on screen...
      for i in icons:      #   For each icon...
        if b.bg == i.name: #    Compare names; match?
          b.iconBg = i     #     Assign Icon to Button
          b.bg     = None  #     Name no longer used; allow garbage collection
        if b.fg == i.name:
          b.iconFg = i
          b.fg     = None

  draw_buttons_for_mode(get_screenMode())

  should_listen = True
  print "Done with Inital Draw"
  # Process touchscreen input
  while should_listen:
      for event in pygame.event.get():
        if(event.type is MOUSEBUTTONDOWN):
          pos = pygame.mouse.get_pos()
          print pos
          plot_points.append(pos[0])
          for b in buttons[get_screenMode()]:
                if b.selected(pos): break
        if event.type == pygame.KEYDOWN:
          if event.key == pygame.K_ESCAPE:
            program_running = False
            should_listen = False
            break
            pygame.quit()
        if event.type == pygame.QUIT:
            program_running = False
            should_listen = False
            break
        if event.type == USEREVENT+1:
          labels["TIME"].draw(screen, time.strftime("%I:%M"), center=True)
          pygame.display.update()
        if event.type == USEREVENT+2:
          ax = fig.gca()
          # We can use this to update the plot "width" until we have enough values for the full width to be taken up.
          # Update the current values. If any kwarg is None, default to the current value, if set, otherwise to rc
          # OR similar, this crashes (http://matplotlib.org/api/figure_api.html#matplotlib.figure.SubplotParams)
          # subplotpars.update(left=0.5)

          ax.plot(plot_points, "-r", antialiased=True)
          ax.axis('off')

          canvas = agg.FigureCanvasAgg(fig)
          canvas.draw()
          renderer = canvas.get_renderer()
          raw_data = renderer.tostring_rgb()
          size = canvas.get_width_height()
          the_graph = pygame.image.fromstring(raw_data, size, "RGB")
          screen.fill(0, ((0,120), (120,320)))
          screen.blit(the_graph, ((0,120), (120,320)))
          pygame.display.flip()
        if event.type == USEREVENT+3:
          # speed = gpsc.fix.speed
          try:
    	    report = session.next()
	    # Wait for a 'TPV' report and display the current time
	    # To see all report data, uncomment the line below
	    # print report
            if report["class"] == "TPV":
              if hasattr(report, "time"):
                print report.time
                # print speed
                labels["SPEED"].draw(screen, str(report.time) + " mph")
          except KeyError:
	    pass

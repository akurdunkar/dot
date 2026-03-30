# See LICENSE file for copyright and license details
# slstatus - suckless status monitor
.POSIX:

VERSION = 0

# paths
PREFIX = /usr/local
MANPREFIX = $(PREFIX)/share/man

X11INC = /usr/X11R6/include
X11LIB = /usr/X11R6/lib

# flags
CPPFLAGS = -I$(X11INC) -D_DEFAULT_SOURCE
CFLAGS   = -std=c99 -pedantic -Wall -Wextra -Os
LDFLAGS  = -L$(X11LIB) -s
LDLIBS   = -lX11

# compiler
CC = cc

REQ = util

all: slstatus

slstatus.o: slstatus.c slstatus.h arg.h config.h $(REQ:=.h)

.c.o:
	$(CC) -o $@ -c $(CPPFLAGS) $(CFLAGS) $<

slstatus: slstatus.o $(REQ:=.o)
	$(CC) -o $@ $(LDFLAGS) $(REQ:=.o) slstatus.o $(LDLIBS)

clean:
	rm -f slstatus slstatus.o $(REQ:=.o)

dist:
	rm -rf "slstatus-$(VERSION)"
	mkdir -p "slstatus-$(VERSION)"
	cp -R LICENSE Makefile README config.h \
	      arg.h slstatus.c $(REQ:=.c) $(REQ:=.h) \
	      "slstatus-$(VERSION)"
	tar -cf - "slstatus-$(VERSION)" | gzip -c > "slstatus-$(VERSION).tar.gz"
	rm -rf "slstatus-$(VERSION)"

install: all
	mkdir -p "$(DESTDIR)$(PREFIX)/bin"
	cp -f slstatus "$(DESTDIR)$(PREFIX)/bin"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/slstatus"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/slstatus"

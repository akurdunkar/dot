# See LICENSE file for copyright and license details
# slstatus - suckless status monitor

VERSION = 0

# paths
PREFIX = /usr/local

X11INC = /usr/X11R6/include
X11LIB = /usr/X11R6/lib

# flags
CPPFLAGS = -I$(X11INC) -D_DEFAULT_SOURCE
CFLAGS   = -std=c99 -pedantic -Wall -Wextra -Os
LDFLAGS  = -L$(X11LIB) -s
LDLIBS   = -lX11

# compiler
CC = cc

# --------------------------------------------------------------------------

BUILD = build
REQ   = util
SRC   = slstatus.c $(REQ:=.c)
OBJ   = $(addprefix $(BUILD)/,$(SRC:.c=.o))

all: $(BUILD)/slstatus

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/slstatus.o: slstatus.h arg.h config.h $(REQ:=.h)
$(BUILD)/util.o: util.h

$(BUILD)/%.o: %.c | $(BUILD)
	$(CC) -o $@ -c $(CPPFLAGS) $(CFLAGS) $<

$(BUILD)/slstatus: $(OBJ)
	$(CC) -o $@ $(LDFLAGS) $(OBJ) $(LDLIBS)

clean:
	rm -rf $(BUILD)

install: all
	mkdir -p "$(DESTDIR)$(PREFIX)/bin"
	cp -f $(BUILD)/slstatus "$(DESTDIR)$(PREFIX)/bin"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/slstatus"

uninstall:
	rm -f "$(DESTDIR)$(PREFIX)/bin/slstatus"

.PHONY: all clean install uninstall

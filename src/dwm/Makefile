# dwm - dynamic window manager
# See LICENSE file for copyright and license details.

# dwm version
VERSION = 6.2

# paths
PREFIX = /usr/local

# Xinerama, comment if you don't want it
XINERAMALIBS  = -lXinerama
XINERAMAFLAGS = -DXINERAMA

# includes and libs
INCS = -I/usr/include/freetype2
LIBS = -lX11 ${XINERAMALIBS} -lXft -lfontconfig

# flags
CPPFLAGS = -D_DEFAULT_SOURCE -D_POSIX_C_SOURCE=200809L -DVERSION=\"${VERSION}\" ${XINERAMAFLAGS}
CFLAGS   = -std=c99 -pedantic -Wall -Wno-deprecated-declarations -O2 ${INCS} ${CPPFLAGS}
LDFLAGS  = ${LIBS}

# compiler and linker
CC = cc

# --------------------------------------------------------------------------

BUILD = build
SRC = drw.c dwm.c util.c
OBJ = $(addprefix ${BUILD}/,${SRC:.c=.o})

all: options ${BUILD}/dwm

options:
	@echo dwm build options:
	@echo "CFLAGS   = ${CFLAGS}"
	@echo "LDFLAGS  = ${LDFLAGS}"
	@echo "CC       = ${CC}"

${BUILD}:
	mkdir -p ${BUILD}

${BUILD}/%.o: %.c config.h | ${BUILD}
	${CC} -c ${CFLAGS} -o $@ $<

${BUILD}/dwm: ${OBJ}
	${CC} -o $@ ${OBJ} ${LDFLAGS}

clean:
	rm -rf ${BUILD}

install: all
	install -Dm755 ${BUILD}/dwm ${DESTDIR}${PREFIX}/bin/dwm
	install -Dm755 dwm.sh ${DESTDIR}${PREFIX}/bin/dwm.sh

uninstall:
	rm -f ${DESTDIR}${PREFIX}/bin/dwm ${DESTDIR}${PREFIX}/bin/dwm.sh

.PHONY: all options clean dist install uninstall

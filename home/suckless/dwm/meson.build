project(
  'dwm',
  'c',
  version: '6.2',
  default_options: [
    'c_std=c99',
    'optimization=s',
  ],
)

# Add compiler arguments
add_project_arguments(
  '-pedantic',
  '-Wno-deprecated-declarations',
  '-D_DEFAULT_SOURCE',
  '-D_BSD_SOURCE',
  '-D_POSIX_C_SOURCE=200809L',
  '-DVERSION="@0@"'.format(meson.project_version()),
  language: 'c',
)

# Find dependencies
x11_dep = dependency('x11', required: true)
xinerama_dep = dependency('xinerama', required: true)
xft_dep = dependency('xft', required: true)
fontconfig_dep = dependency('fontconfig', required: true)

# Add Xinerama flag
add_project_arguments('-DXINERAMA', language: 'c')

# Source files
sources = files(
  'drw.c',
  'dwm.c',
  'util.c',
)

# Build executable
executable(
  'dwm',
  sources,
  dependencies: [
    x11_dep,
    xinerama_dep,
    xft_dep,
    fontconfig_dep,
  ],
  install: true,
)

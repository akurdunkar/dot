#include <X11/XF86keysym.h>

/* appearance */

static const unsigned int borderpx         =   0;     /* border pixel of windows */
static const unsigned int gappx            =   0;     /* gaps between windows */
static const unsigned int snap             =   32;    /* snap pixel */
static const unsigned int systraypinning   =   0;     /* 0: sloppy systray follows selected monitor, >0: pin systray to monitor X */
static const unsigned int systrayonleft    =   0;     /* 0: systray in the right corner, >0: systray on left of status text */
static const unsigned int systrayspacing   =   4;     /* systray spacing */
static const int systraypinningfailfirst   =   1;     /* 1: if pinning fails, display systray on the first monitor, False: display systray on the last monitor*/
static const int showsystray               =   1;     /* 0 means no systray */
static const int showbar                   =   1;     /* 0 means no bar */
static const int topbar                    =   1;     /* 0 means bottom bar */
static const int vertpad                   =   0;     /* vertical padding of bar */
static const int sidepad                   =   0;     /* horizontal padding of bar */
static const int DFW                       =   800;
static const int DFH                       =   600;
static const int DFX                       =   550;
static const int DFY                       =   250;
static const char *fonts[]                 =   { "Ubuntu Mono Nerd Font:size=12:style=Normal" };
static const char col_statusbar_fg[]       =   "#ffffff";
static const char col_statusbar_bg[]       =   "#000000";
static const char col_primary_fg[]         =   "#ffffff";
static const char col_primary_bg[]         =   "#1c4289";
static const char col_border[]             =   "#000000";
static const char col_border_sel[]         =   "#1c4289";
static const int BORDER_PX = 0;


static const char *colors[][3]      = {
    /*              fg                 bg                 border   */
   [SchemeNorm] = { col_statusbar_fg,  col_statusbar_bg, col_border},
   [SchemeSel]  = { col_primary_fg,    col_primary_bg  , col_border_sel},
};

/* tagging */
static const char *tags[] = {"1", "2", "3", "4", "5", "6", "7", "8", "9" };
static const Rule rules[] = {

  /* class               instance    title       tags mask   isfloating   monitor    float x,y,w,h              floatborderpx      scratchKEY*/

 { "Gimp",               NULL,       NULL,      1<<4,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Inkscape",           NULL,       NULL,      1<<4,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Firefox",            NULL,       NULL,      3,          0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "TelegramDesktop",    NULL,       NULL,      1<<2,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "qBittorrent",        NULL,       NULL,      1<<3,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "zoom",               NULL,       NULL,      1<<6,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "figma-linux",        NULL,       NULL,      1<<4,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "discord",            NULL,       NULL,      1<<7,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "VSCodium",           NULL,       NULL,      1<<2,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Steam",              NULL,       NULL,      1<<3,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Tk",                 NULL,       NULL,      0,          1,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Pavucontrol",        NULL,       NULL,      1<<8,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Pulseeffects",       NULL,       NULL,      1<<8,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},
 { "Blender",            NULL,       NULL,      1<<4,       0,           -1 ,       DFX,   DFY,   DFW,   DFH,             5,         0},

                                                 /* Scratch Pads */

 { NULL,    NULL,     "aditya - Thunar",      0,      1,           -1 ,       DFX,         DFY,   DFW,         DFH,     BORDER_PX,   'n'},
 { NULL,    NULL,     "scratchpad",           0,      1,           -1,        DFX,         DFY,   DFW,         DFH,     BORDER_PX,   's'},
 { NULL,    NULL,     "gomp",                 0,      1,           -1,        DFX - 50 ,   DFY,   DFW + 50 ,   DFH,     BORDER_PX,   'y'},
 { NULL,    NULL,     "gspt",                 0,      1,           -1,        DFX - 50 ,   DFY,   DFW + 50 ,   DFH,     BORDER_PX,   'g'},
 { NULL,    NULL,     "tremc",                0,      1,           -1,        DFX - 50 ,   DFY,   DFW + 50 ,   DFH,     BORDER_PX,   't'},
 { NULL,    NULL,     "Select Color",         0,      1,           -1,        DFX - 50 ,   DFY,   DFW + 50 ,   DFH,     BORDER_PX,   'c'},
 { NULL,    NULL,     "Ideas",                0,      1,           -1,        DFX - 50 ,   DFY,   DFW + 50 ,   DFH,     BORDER_PX,   'i'},

};

/* layout(s) */
static const float mfact     = 0.50; /* factor of master area size [0.05..0.95] */
static const int nmaster     = 1;    /* number of clients in master area */
static const int resizehints = 1;    /* 1 means respect size hints in tiled resizals */

static const Layout layouts[] = {
    /* symbol     arrange function */
    { " ",      tile },    /* first entry is default */
    { "󰥛 ",      NULL },    /* no layout function means floating behavior */
    { "󰝤 ",      monocle },
    { "󱗼",       grid },
    { " ",      spiral },
    { " ",      bstack },
};

/* key definitions */
#define MODKEY Mod4Mask
#define TAGKEYS(KEY,TAG) \
    { MODKEY,                       KEY,      view,           {.ui = 1 << TAG} }, \
    { Mod1Mask,                     KEY,      toggleview,     {.ui = 1 << TAG} }, \
    { MODKEY|ShiftMask,             KEY,      tag,            {.ui = 1 << TAG} }, \
    { MODKEY|ControlMask,           KEY,      toggletag,      {.ui = 1 << TAG} },

/* helper for spawning shell commands in the pre dwm-5.0 fashion */
#define SHCMD(cmd) { .v = (const char*[]){ "/bin/bash", "-c", cmd, NULL } }

/* commands */
static const char *termcmd[]         = { "/usr/bin/alacritty", NULL };
static const char *webcmd[]             = { "/usr/bin/microsoft-edge", NULL };
static const char *torrentclicmd[]      = { "t", "alacritty", "-t", "tremc" , "-e", "tremc", NULL};
static const char *filemanagercmd[]     = { "n", "/usr/bin/thunar", NULL };
static const char *colorchoosercmd[]    = { "c", "/usr/bin/kcolorchooser", NULL };

static Key keys[] = {
   /* modifier                               key                          function        argument */
  { MODKEY,                                 XK_u,                        spawn,                 {.v = webcmd} },
  { MODKEY,                                 XK_Return,                   spawn,                 {.v = termcmd } },
  { MODKEY,                                 XK_e,                        togglescratch,         {.v = filemanagercmd } },
  { MODKEY,                                 XK_q,                        togglescratch,         {.v = torrentclicmd } },
  { MODKEY|ControlMask|ShiftMask,           XK_c,                        togglescratch,         {.v = colorchoosercmd } },
  { 0,                                      XF86XK_AudioPrev,            spawn,                 SHCMD("mpc prev")},
  { 0,                                      XF86XK_AudioNext,            spawn,                 SHCMD("mpc next")},
  { 0,                                      XF86XK_AudioPlay,            spawn,                 SHCMD("mpc toggle")},
  { 0,                                      XF86XK_AudioStop,            spawn,                 SHCMD("mpc stop")},
  { 0,                                      XF86XK_AudioLowerVolume,     spawn,                 SHCMD("pamixer -d 5")},
  { 0,                                      XF86XK_AudioRaiseVolume,     spawn,                 SHCMD("pamixer -i 5")},
  { MODKEY,                                 XK_F10,                      spawn,                 SHCMD("xbacklight -inc 10")},
  { MODKEY,                                 XK_F9,                       spawn,                 SHCMD("xbacklight -dec 10")},
  { 0,                                      XF86XK_MonBrightnessUp,      spawn,                 SHCMD("xbacklight -inc 10")},
  { 0,                                      XF86XK_MonBrightnessDown,    spawn,                 SHCMD("xbacklight -dec 10")},
  { MODKEY|ShiftMask,                       XK_F5,                       spawn,                 SHCMD("reload_keys")},
  { MODKEY,                                 XK_v,                        spawn,                 SHCMD("copyq menu")},
  { MODKEY,                                 XK_t,                        setlayout,             {.v = &layouts[0]} },
  { MODKEY,                                 XK_m,                        setlayout,             {.v = &layouts[2]} },
  { MODKEY,                                 XK_g,                        setlayout,             {.v = &layouts[3]} },
  { MODKEY,                                 XK_s,                        setlayout,             {.v = &layouts[4]} },
  { MODKEY,                                 XK_b,                        setlayout,             {.v = &layouts[5]} },
  { Mod1Mask,                               XK_b,                        togglebar,             {0} },
  { MODKEY,                                 XK_j,                        focusstackvis,         {.i = +1 } },
  { MODKEY,                                 XK_k,                        focusstackvis,         {.i = -1 } },
  { MODKEY|ShiftMask,                       XK_j,                        focusstackhid,         {.i = +1 } },
  { MODKEY|ShiftMask,                       XK_k,                        focusstackhid,         {.i = -1 } },
  { MODKEY|ShiftMask,                       XK_minus,                    incnmaster,            {.i = +1 } },
  { MODKEY,                                 XK_d,                        incnmaster,            {.i = -1 } },
  { MODKEY,                                 XK_h,                        setmfact,              {.f = -0.05} },
  { MODKEY,                                 XK_l,                        setmfact,              {.f = +0.05} },
  { MODKEY,                                 XK_Tab,                      view,                  {0} },
  { MODKEY|ShiftMask,                       XK_c,                        killclient,            {0} },
  { MODKEY,                                 XK_c,                        killclient,            {0} },
  { MODKEY,                                 XK_f,                        togglefullscr,         {0} },
  { MODKEY,                                 XK_m,                        zoom,                  {0} },
  { MODKEY,                                 XK_0,                        view,                  {.ui = ~0 } },
  { MODKEY|ShiftMask,                       XK_0,                        tag,                   {.ui = ~0 } },
  { MODKEY,                                 XK_comma,                    focusmon,              {.i = -1 } },
  { MODKEY,                                 XK_period,                   focusmon,              {.i = +1 } },
  { MODKEY|ShiftMask,                       XK_comma,                    tagmon,                {.i = -1 } },
  { MODKEY|ShiftMask,                       XK_period,                   tagmon,                {.i = +1 } },
  { MODKEY,                                 XK_minus,                    setgaps,               {.i = -1 } },
  { MODKEY,                                 XK_equal,                    setgaps,               {.i = +1 } },
  { MODKEY|ShiftMask,                       XK_equal,                    setgaps,               {.i = 0  } },
  { MODKEY|ShiftMask,                       XK_space,                    togglefloating,        {0} },
  { MODKEY,                                 XK_s,                        show,                  {0} },
  { MODKEY,                                 XK_o,                        hide,                  {0} },
  TAGKEYS(                                  XK_1,                        0)
  TAGKEYS(                                  XK_2,                        1)
  TAGKEYS(                                  XK_3,                        2)
  TAGKEYS(                                  XK_4,                        3)
  TAGKEYS(                                  XK_5,                        4)
  TAGKEYS(                                  XK_6,                        5)
  TAGKEYS(                                  XK_7,                        6)
  TAGKEYS(                                  XK_8,                        7)
  TAGKEYS(                                  XK_9,                        8)
  { MODKEY|ShiftMask|ControlMask,           XK_q,                        quit,           {0} },
};

/* button definitions */
/* click can be ClkTagBar, ClkLtSymbol, ClkStatusText, ClkWinTitle, ClkClientWin, or ClkRootWin */
static Button buttons[] = {
    /* click                event mask      button          function        argument */
    { ClkLtSymbol,          0,              Button1,        setlayout,      {0} },
    { ClkLtSymbol,          0,              Button3,        setlayout,      {.v = &layouts[2]} },
    { ClkWinTitle,          0,              Button1,        togglewin,      {0} },
    { ClkWinTitle,          0,              Button2,        zoom,           {0} },
    { ClkStatusText,        0,              Button2,        spawn,          {.v = termcmd } },
    { ClkClientWin,         MODKEY,         Button1,        movemouse,      {0} },
    { ClkClientWin,         MODKEY,         Button2,        togglefloating, {0} },
    { ClkClientWin,         MODKEY,         Button3,        resizemouse,    {0} },
    { ClkTagBar,            0,              Button1,        view,           {0} },
    { ClkTagBar,            0,              Button3,        toggleview,     {0} },
    { ClkTagBar,            MODKEY,         Button1,        tag,            {0} },
    { ClkTagBar,            MODKEY,         Button3,        toggletag,      {0} },
};

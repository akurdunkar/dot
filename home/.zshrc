autoload -U colors && colors

# E_ZPROF="true" # Enable Profiling

! [[ -z $E_ZPROF ]] && zmodload zsh/zprof

setopt HIST_SAVE_NO_DUPS

HISTSIZE=100000
SAVEHIST=100000
HISTORY_DIR="$HOME/.cache/zsh/"
HISTFILE=$HISTORY_DIR/history
! [[ -d "$HISTORY_DIR" ]] && mkdir "$HISTORY_DIR"

# Basic auto/tab complete:
autoload -U compinit
zstyle ':completion:*' menu select
zmodload zsh/complist
compinit

# Enable bash completions
autoload -U +X bashcompinit && bashcompinit

# Include hidden files.
_comp_options+=(globdots)

# vi mode
bindkey -v

export KEYTIMEOUT=1

# Keybindings
bindkey '^H' backward-kill-word
# Use vim keys in tab complete menu:
bindkey -M menuselect 'h' vi-backward-char
bindkey -M menuselect 'k' vi-up-line-or-history
bindkey -M menuselect 'l' vi-forward-char
bindkey -M menuselect 'j' vi-down-line-or-history
bindkey -v '^?' backward-delete-char
bindkey '^R' history-incremental-search-backward

# Change cursor shape for different vi modes.
function zle-keymap-select {
  if [[ ${KEYMAP} == vicmd ]] ||
     [[ $1 = 'block' ]]; then
    echo -ne '\e[1 q'
  elif [[ ${KEYMAP} == main ]] ||
       [[ ${KEYMAP} == viins ]] ||
       [[ ${KEYMAP} = '' ]] ||
       [[ $1 = 'beam' ]]; then
    echo -ne '\e[5 q'
  fi
}

zle -N zle-keymap-select
zle-line-init() {
    zle -K viins # initiate `vi insert` as keymap (can be removed if `bindkey -V` has been set elsewhere)
    echo -ne "\e[5 q"
}
zle -N zle-line-init
echo -ne '\e[5 q' # Use beam shape cursor on startup.
preexec() { echo -ne '\e[5 q' ;} # Use beam shape cursor for each new prompt.

#-----------------------------------------------------------------------------

source $HOME/common.sh
envm

# Prompt Starts---------------------------------------------------------------

local BRANCH_COLOR=red
local PROMPT_COLOR=yellow
local FILE_COLOR=blue
local HOST_COLOR=green

## autoload vcs and colors
autoload -Uz vcs_info
autoload -U colors && colors

# enable only git
zstyle ':vcs_info:*' enable git

# setup a hook that runs before every ptompt.
precmd_vcs_info() { vcs_info }
precmd_functions+=( precmd_vcs_info )
setopt prompt_subst

zstyle ':vcs_info:git:*' formats " %B%{$fg[$BRANCH_COLOR]%}%b"

PROMPT="%{$fg[$HOST_COLOR]%}[ %M ] %{$fg[$FILE_COLOR]%}%B%2~"
PROMPT+="\$vcs_info_msg_0_ % %{$fg[$PROMPT_COLOR]%}%% %{$reset_color%}"

# Prompt Ends-----------------------------------------------------------------

! [[ -z $E_ZPROF ]] && zprof > $HOME/zsh.log

#!/bin/bash

# Common functions and utilities that can be shared between bash and zsh

#-(Source Files)--------------------------------------------------------------
__source__() {
	local hostname
	hostname=$(hostname)
	local file="$HOME/$hostname/$1"

	# Check if hostname-specific file exists
	if [[ -f "$file" ]]; then
		# shellcheck source=/dev/null
		source "$HOME/$1" # Source common file first
		# shellcheck source=/dev/null
		source "$file"
	else
		echo "Unable to find priv files for $hostname.."
	fi
}

__source__ ".env"
__source__ ".alias"
__source__ ".rc"

#-(Create files/folders that don't exist but are required )-------------------

# Z script
Z_SH_PATH="$HOME/z.sh"
Z_SH_LINK="https://raw.githubusercontent.com/rupa/z/master/z.sh"
if ! [[ -r "$Z_SH_PATH" ]]; then
	wget "$Z_SH_LINK" -O "$Z_SH_PATH"
else
	# shellcheck source=/dev/null
	source "$Z_SH_PATH"
fi

# Create directories that don't exist
! [[ -d "$VENV_DIR" ]] && mkdir "$VENV_DIR"
! [[ -d "$CODE_DIR" ]] && mkdir "$CODE_DIR"
! [[ -d "$NOTES_DIR" ]] && mkdir "$NOTES_DIR"
! [[ -d "$STASH_DIR" ]] && mkdir "$STASH_DIR"

! [[ -r "$NVM_DIR" ]] &&
	curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash &&
	nvm install node &&
	nvm use node

#-----------------------------------------------------------------------------

cmd_exists() {
	command -v "$1" 1>/dev/null 2>/dev/null && return 0
	return 1
}

fd_command() {
	cmd_exists fd && printf "fd" || printf "fdfind"
	printf " --color=never"
}

# Setting fd as the default source for fzf (respects .gitignore)
FZF_DEFAULT_COMMAND="$(fd_command) --type f --strip-cwd-prefix"
export FZF_DEFAULT_COMMAND

fzf_cmd() {
	local fzf_height
	local fzf_opts

	fzf_height=7
	fzf_opts="--height $fzf_height --border=none --info=hidden --color=dark --reverse --ansi"

	eval "fzf $fzf_opts"
}

rg_cmd() {
	rg --color=always --colors 'match:fg:white' --column --line-number --hidden --ignore-case --no-heading .
}

dmenu_cmd() {
	dmenu -i -f -l 10
}

fk() {
	[[ $1 == "" ]] && return 1
	pgrep -f "$1" | fzf_cmd | xargs -r kill
}

venv() {
	case "$1" in
	"new")
		if [[ "$2" != "" ]]; then
			virtualenv "$VENV_DIR/$2" && {
				# shellcheck source=/dev/null
				source "$VENV_DIR/$2/bin/activate"
			}
		else
			echo "Empty Name Provided!"
		fi
		;;
	"remove")
		if [[ "$2" != "" ]]; then
			\rm -rf "${VENV_DIR:?}/$2" &&
				echo "Removed $2 Succesfully!"
		else
			echo "Empty Name Provided!"
		fi
		command -v deactivate && deactivate
		;;
	"-f")
		local sel
		sel="$(find "$VENV_DIR" -maxdepth 1 -mindepth 1 -type d | fzf_cmd)"
		if [[ "$sel" != "" ]]; then
			# shellcheck source=/dev/null
			source "$sel/bin/activate"
		fi
		;;
	"source")
		# shellcheck source=/dev/null
		source "$VENV_DIR/$2/bin/activate"
		;;
	esac
}

tl() {
	local session
	session="$(tmux list-sessions | fzf_cmd | awk -F: '{print $1}')"
	[[ "$session" != "" ]] && tmux attach-session -t "$session"
}

note() {
	if [[ "$1" == "-d" ]]; then
		"$EDITOR" "$NOTES_DIR/$(date "+%a_%d_%b.md")"
	elif [[ "$1" == "-f" ]]; then
		all_files "$NOTES_DIR" | fzf_cmd | xargs -r -d '\n' "$EDITOR"
	elif [[ "$1" == "-g" ]]; then
		cd "$NOTES_DIR" || return
	elif [[ "$1" != "" ]]; then
		if [[ "$1" != *.md ]]; then
			"$EDITOR" "$NOTES_DIR/$1.md"
		else
			"$EDITOR" "$NOTES_DIR/$1"
		fi
	fi
}

fg() {
	local selection
	selection=$(rg_cmd | fzf_cmd | head -n1)
	if [[ -n "$selection" ]]; then
		# Expected format: filename:line:optional_text
		file=$(echo "$selection" | cut -d':' -f1)
		line=$(echo "$selection" | cut -d':' -f2)

		# Fallback if no line number is found
		if [[ -z "$line" ]]; then
			line=1
		fi

		# Open file in "$EDITOR" at the line number
		"$EDITOR" "$file" +"$line"
	fi
}

cco() {
	if [[ "$1" == "-m" ]]; then
		printf "Making Directory %s\n" "$2"
		mkdir "$CODE_DIR/$2"
		printf "Changing Directory to %s\n" "$2"
		cd "$CODE_DIR/$2" || return
	elif [[ "$1" == "-f" ]]; then
		dir=$(find "$CODE_DIR" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | fzf_cmd)
		cd "$CODE_DIR/$dir" || return
	elif [[ "$1" == "-rm" || "$1" == "rm" ]]; then
		\rm -ivr "${CODE_DIR:?}/$2"
	elif [[ "$1" == "-c" ]]; then
		cd "$CODE_DIR/$2" || return
	else
		f="$1"
		shift 1>/dev/null 2>/dev/null
		z "$CODE_DIR/$f" "$@"
	fi
}

fs() {
	fzf_cmd | xargs -r -d '\n' "$EDITOR"
}

all_files() {
	local fd_cmd
	fd_cmd=$(fd_command)
	eval "$fd_cmd . $1"
}

conf() {
	local dir="NOT SET"
	local GO_TO_DIR=0
	# Args
	for i in "$@"; do
		if [[ "$i" == "-g" ]]; then
			GO_TO_DIR=1
		else
			dir="$i"
		fi
	done

	# Dir
	if [[ "$dir" == "NOT SET" ]]; then
		dir=$(find "$HOME/.config" -maxdepth 1 -mindepth 1 -printf '%f\n' | fzf_cmd)
	fi

	if [[ "$GO_TO_DIR" == "1" ]]; then
		cd "$HOME/.config/$dir" || return
	else
		"$EDITOR" "$HOME/.config/$dir"
	fi
}

fn() {
	all_files "$HOME/.config/nvim/" | fzf_cmd | xargs -r -d '\n' "$EDITOR"
}

envm() {
	# Node Version Manager
	# shellcheck source=/dev/null
	[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" # This loads nvm
	# shellcheck source=/dev/null
	[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion" # This loads nvm bash_completion
}

epyenv() {
	export PYENV_ROOT="$HOME/.pyenv"
	[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
	eval "$(pyenv init -)"
}

sb() {
	if [[ -n "$ZSH_VERSION" ]]; then
		# shellcheck source=/dev/null
		source "$HOME/.zshrc"
	elif [[ -n "$BASH_VERSION" ]]; then
		# shellcheck source=/dev/null
		source "$HOME/.bashrc"
	fi
}

stash() {
	# Create stash directory if it doesn't exist
	[[ ! -d "$STASH_DIR" ]] && mkdir -p "$STASH_DIR"

	case "$1" in
	"-l" | "list")
		# List all stashed files with timestamps
		if [[ -n "$(ls -A "$STASH_DIR" 2>/dev/null)" ]]; then
			find "$STASH_DIR" -maxdepth 1 -type f -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2- | xargs -I {} ls -lh {}
		else
			echo "Stash is empty"
		fi
		;;
	"-r" | "restore")
		# Restore a specific file
		if [[ -n "$2" ]]; then
			local filename
			filename=$(basename "$2")
			if [[ -f "$STASH_DIR/$filename" ]]; then
				cp "$STASH_DIR/$filename" ./"$filename"
				echo "Restored: $filename"
			else
				echo "File not found in stash: $filename"
				return 1
			fi
		else
			echo "Usage: stash -r <filename>"
			return 1
		fi
		;;
	"-f")
		# Fuzzy find and restore a stashed file
		local sel
		sel="$(all_files "$STASH_DIR" | fzf_cmd)"
		if [[ -n "$sel" ]]; then
			local filename
			filename=$(basename "$sel")
			cp "$sel" ./"$filename"
			echo "Restored: $filename"
		fi
		;;
	"-rm" | "remove")
		# Remove a stashed file
		if [[ -n "$2" ]]; then
			local filename
			filename=$(basename "$2")
			if [[ -f "$STASH_DIR/$filename" ]]; then
				\rm -i "$STASH_DIR/$filename"
			else
				echo "File not found in stash: $filename"
				return 1
			fi
		else
			echo "Usage: stash -rm <filename>"
			return 1
		fi
		;;
	"-g")
		# Go to stash directory
		cd "$STASH_DIR" || return
		;;
	"-h" | "help" | "")
		# Show help
		cat <<EOF
Usage: stash [OPTION] [FILE]

Stash files in a temporary directory for later use.

Options:
  <file>           Stash a file or directory
  -l, list         List all stashed files
  -r, restore      Restore a specific file to current directory
  -f               Fuzzy find and restore a stashed file
  -rm, remove      Remove a stashed file from stash
  -g               Go to stash directory
  -h, help         Show this help message

Environment:
  STASH_DIR        Stash directory location (default: $HOME/.stash)
EOF
		;;
	*)
		# Stash the specified file or directory
		if [[ -e "$1" ]]; then
			local filename
			local timestamp
			local target
			filename=$(basename "$1")
			timestamp=$(date "+%Y%m%d_%H%M%S")
			target="$STASH_DIR/${filename}.${timestamp}"

			cp -r "$1" "$target"
			echo "Stashed: $filename -> $(basename "$target")"
		else
			echo "File or directory not found: $1"
			return 1
		fi
		;;
	esac
}

source $HOME/.completions

-- Globals
vim.g["vscode_style"]                  = "dark"
vim.g["color_coded_enabled "]          = 1
vim.g["go_def_mapping_enabled"]        = false
vim.g["fzf_preview_window"]            = {}
vim.g["fzf_layout"]                    = { down = '20%' }
vim.g["everforest_background"]         = 'hard'
vim.g["everforest_better_performance"] = 1

if vim.fn.has("wsl") == 1 then
    vim.cmd [[
        let g:clipboard = {
          \   'name': 'WslClipboard',
          \   'copy': {
          \      '+': 'clip.exe',
          \      '*': 'clip.exe',
          \    },
          \   'paste': {
          \      '+': 'powershell.exe -c [Console]::Out.Write($(Get-Clipboard -Raw).tostring().replace("`r", ""))',
          \      '*': 'powershell.exe -c [Console]::Out.Write($(Get-Clipboard -Raw).tostring().replace("`r", ""))',
          \   },
          \   'cache_enabled': 0,
          \ }
    ]]
end

vim.opt.background = "dark"
vim.opt.termguicolors = true

vim.cmd [[
    syntax enable
    color github_dark
    syntax on
]]

local COLUMNS = 80
-- vim.opt.colorcolumn=vim.fn.join(vim.fn.range(COLUMNS, 999),",")
vim.opt.colorcolumn = { COLUMNS }
vim.opt.cmdheight = 1
vim.opt.hidden = true       -- Required to keep multiple buffers open multiple buffers
vim.opt.wrap = false
vim.opt.pumheight = 10      -- Makes popup menu smaller
vim.opt.splitbelow = true   -- Horizontal splits will automatically be below
vim.opt.splitright = true   -- Vertical splits will automatically be to the right
vim.opt.swapfile = false
vim.opt.showmode = false    -- We don't need to see things like -- INSERT -- anymore
vim.opt.backup = false      -- This is recommended by coc
vim.opt.writebackup = false -- This is recommended by coc
vim.opt.updatetime = 300    -- Faster completion
vim.opt.timeoutlen = 500    -- By default timeoutlen is 1000 ms
vim.opt.winbar = "%m %f"
vim.opt.nu = true
vim.opt.errorbells = false
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.shiftwidth = 4
vim.opt.smartindent = true
vim.opt.incsearch = true
vim.opt.compatible = false
vim.opt.cursorline = true
vim.opt.showmode = false
vim.opt.completeopt = "menu"
vim.opt.spelloptions = "camel"
vim.opt.expandtab = true
vim.opt.laststatus = 0
vim.opt.mouse = "a"

-- Highlights
vim.cmd("hi DiagnosticVirtualTextError gui=italic guifg=#a84032")
vim.cmd("hi DiagnosticVirtualTextInfo gui=italic guifg=#3277a8")
vim.cmd("hi DiagnosticVirtualTextWarn gui=italic guifg=#d1cf47")
vim.cmd("hi DiagnosticVirtualTextOk gui=italic guifg=#3277a8")

vim.cmd("hi Winbar guibg=None guifg=white")
vim.cmd("hi WinbarNC guibg=None guifg=grey")
vim.cmd("hi NonText guifg=grey")

-- vim.cmd("hi Normal guibg=black")
-- vim.cmd("hi LineNr guibg=None")
-- vim.cmd("hi SignColumn guibg=None")
-- vim.cmd("hi EndOfBuffer guibg=None")
-- vim.cmd("hi NormalNC guibg=None")

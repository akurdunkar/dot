-- Globals

vim.g["color_coded_enabled "]          = 1
vim.g["go_def_mapping_enabled"]        = false
vim.g["fzf_preview_window"]            = {}
vim.g["fzf_layout"]                    = { down = '25%' }

-- WSL Interopt

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

-- Colors

vim.cmd [[
    syntax enable
    color scruber
    syntax on
]]

-- Options

vim.opt.background = "dark"
vim.opt.termguicolors = true
vim.opt.colorcolumn = { 80 }
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

local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
    vim.fn.system({
        "git",
        "clone",
        "--filter=blob:none",
        "https://github.com/folke/lazy.nvim.git",
        "--branch=stable", -- latest stable release
        lazypath,
    })
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
    'tpope/vim-commentary',
    {
        "lukas-reineke/indent-blankline.nvim",
        config = function()
            require("ibl").setup()
        end
    },
    'dstein64/vim-startuptime',

    { 'junegunn/fzf',    build = function() vim.cmd('call fzf#install()') end },
    { 'junegunn/fzf.vim' },

    -- Color Schemes
    -- 'mhartington/oceanic-next',
    -- 'navarasu/onedark.nvim',
    -- 'folke/tokyonight.nvim',
    -- 'Mofiqul/vscode.nvim',
    -- 'projekt0n/github-nvim-theme',
    -- 'sainnhe/everforest',
    -- 'sainnhe/sonokai',
    -- 'RRethy/nvim-base16',
    -- "rebelot/kanagawa.nvim",
    -- { "ellisonleao/gruvbox.nvim",     dependencies = { "rktjmp/lush.nvim" } },
    -- { "briones-gabriel/darcula-solid.nvim", dependencies = "rktjmp/lush.nvim" },
    -- 'nyoom-engineering/oxocarbon.nvim',
    'ishan9299/nvim-solarized-lua',
    -- 'savq/melange-nvim',
    -- 'yorickpeterse/vim-paper',
    -- 'yorickpeterse/nvim-grey',
    -- 'davidosomething/vim-colors-meh',
    -- 'Shatur/neovim-ayu',
    -- 'https://gitlab.com/madyanov/gruber.vim',
    -- 'aditya-K2/scruber.vim',
    -- 'vim/colorschemes',
    -- "craftzdog/solarized-osaka.nvim",

    { 'iamcco/markdown-preview.nvim',           build = 'cd app && yarn install' },
    {
        'lewis6991/gitsigns.nvim',
        config = function()
            require('gitsigns').setup {
                signs = {
                    add = { text = '+' },
                    change = { text = '~' },
                },
            }
        end
    },

    -- Tree Sitter
    {
        'nvim-treesitter/nvim-treesitter',
        build = ':TSUpdate',
        config = function()
            -- treesitter highlighting
            require 'nvim-treesitter.configs'.setup {
                ensure_installed = {
                    "go", "haskell",
                    "cpp", "c",
                    "lua", "vim", "vimdoc",
                    "json", "jsonc",
                    "python", "dart",
                    "typescript", "javascript", "html", "css", "java"
                },
                highlight = { enable = true } }
        end
    },
    { 'nvim-treesitter/playground',             cmd = "TSPlaygroundToggle" },
    { 'nvim-treesitter/nvim-treesitter-context' },

    -- Lsp
    'neovim/nvim-lspconfig',
    {
        'williamboman/mason.nvim',
        config = function()
            require("mason").setup()
        end
    },
    {
        'williamboman/mason-lspconfig.nvim',
        config = function()
            require("mason-lspconfig").setup({
                ensure_installed = {
                    "clangd",
                    "vimls",
                    "pyright",
                    "gopls",
                    "lua_ls",
                    "yamlls",
                    "cssls",
                    "html",
                    "mesonlsp",
                    "jsonls",
                }
            })
        end
    },

    -- Cmp
    'hrsh7th/nvim-cmp',
    'hrsh7th/cmp-buffer',
    'hrsh7th/cmp-path',
    'hrsh7th/cmp-nvim-lua',
    'hrsh7th/cmp-nvim-lsp',
    'onsails/lspkind-nvim',

    'aditya-K2/spellfloat',
    -- {
    --     'aditya-K2/termtoggle.nvim',
    --     config = function()
    --         require('termtoggle').setup()
    --     end
    -- },

    { 'fatih/vim-go', ft = "go" },

    --Maximizer
    'szw/vim-maximizer',

    -- Tmux Navigator
    {
        "christoomey/vim-tmux-navigator",
        cmd = {
            "TmuxNavigateLeft",
            "TmuxNavigateDown",
            "TmuxNavigateUp",
            "TmuxNavigateRight",
            "TmuxNavigatePrevious",
            "TmuxNavigatorProcessList",
        },
        keys = {
            { "<M-h>", "<cmd>TmuxNavigateLeft<cr>" },
            { "<M-j>", "<cmd>TmuxNavigateDown<cr>" },
            { "<M-k>", "<cmd>TmuxNavigateUp<cr>" },
            { "<M-l>", "<cmd>TmuxNavigateRight<cr>" },
            { "<M-\\>", "<cmd>TmuxNavigatePrevious<cr>" },
        },
    },
})

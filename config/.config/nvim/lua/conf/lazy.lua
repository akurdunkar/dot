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

local treesitter_file_pattern = {
    "cpp", "c",
    "lua", "vim", "vimdoc",
    "json", "yaml",
    "python", "go"
}

require("lazy").setup({
    'tpope/vim-commentary',
    {
        "lukas-reineke/indent-blankline.nvim",
        config = function()
            require("ibl").setup()
        end
    },
    'dstein64/vim-startuptime',

    { 'junegunn/fzf' },
    { 'junegunn/fzf.vim' },

    -- Color scheme
    'aditya-K2/scruber.vim',

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
        branch = 'main',
        lazy = false,
        build = function()
            require('nvim-treesitter').install(treesitter_file_pattern):wait(300000)
        end,
        config = function()
            require('nvim-treesitter').setup {}
            vim.api.nvim_create_autocmd('FileType', {
                pattern = treesitter_file_pattern,
                callback = function() vim.treesitter.start() end,
            })
        end
    },
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

    { 'fatih/vim-go',                           ft = "go" },

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
            { "<M-h>",  "<cmd>TmuxNavigateLeft<cr>" },
            { "<M-j>",  "<cmd>TmuxNavigateDown<cr>" },
            { "<M-k>",  "<cmd>TmuxNavigateUp<cr>" },
            { "<M-l>",  "<cmd>TmuxNavigateRight<cr>" },
            { "<M-\\>", "<cmd>TmuxNavigatePrevious<cr>" },
        },
    },
})

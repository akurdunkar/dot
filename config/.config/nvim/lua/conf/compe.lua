local lspkind = require "lspkind"
lspkind.init()
local cmp = require "cmp"

cmp.setup {
    mapping = {
        ["<C-d>"] = cmp.mapping.scroll_docs(-4),
        ["<C-f>"] = cmp.mapping.scroll_docs(4),
        ["<C-e>"] = cmp.mapping.close(),
        ["<C-p>"] = cmp.mapping.select_prev_item(),
        ["<C-n>"] = cmp.mapping.select_next_item(),
        ["<c-y>"] = cmp.mapping.confirm {
            behavior = cmp.ConfirmBehavior.Insert,
            select = true,
        },

        ["<c-space>"] = cmp.mapping.complete(),

    },

    sources = {
        { name = "nvim_lua" },
        { name = "nvim_lsp" },
        { name = "path" },
        { name = "buffer" }
    },

    snippet = {
        expand = function(args)
            require("luasnip").lsp_expand(args.body)
        end,
    },

    experimental = {
        -- the new menu
        ghost_text = true,
    },
    -- view = { entries = 'native' },
    formatting = {
        format = lspkind.cmp_format({ with_text = true, maxwidth = 50 })
    }
}

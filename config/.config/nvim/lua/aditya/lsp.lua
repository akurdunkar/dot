local servers = {
    "clangd",
    "vimls",
    "pyright",
    "gopls",
    "lua_ls",
    "yamlls",
    "cssls",
    "html",
    "mesonlsp",
    "jsonls"
}

-- Use an on_attach function to only map the following keys
-- after the language server attaches to the current buffer
local on_attach = function(_, bufnr)
    local function buf_set_keymap(...) vim.api.nvim_buf_set_keymap(bufnr, ...) end
    -- local function buf_set_option(...) vim.api.nvim_buf_set_option(bufnr, ...) end
    local opts = { noremap = true, silent = true }

    buf_set_keymap('n', 'gD', '<Cmd>lua vim.lsp.buf.declaration()<CR>', opts)
    buf_set_keymap('n', 'gd', '<Cmd>lua vim.lsp.buf.definition()<CR>', opts)
    buf_set_keymap('n', 'gi', '<cmd>lua vim.lsp.buf.implementation()<CR>', opts)
    buf_set_keymap('n', 'K', '<Cmd>lua vim.lsp.buf.hover()<CR>', opts)
    buf_set_keymap('n', '<C-k>', '<cmd>lua vim.lsp.buf.signature_help()<CR>', opts)
    buf_set_keymap('n', '<space>D', '<cmd>lua vim.lsp.buf.type_definition()<CR>', opts)
    buf_set_keymap('n', '<space>rn', '<cmd>lua vim.lsp.buf.rename()<CR>', opts)
    buf_set_keymap('n', '<space>ca', '<cmd>lua vim.lsp.buf.code_action()<CR>', opts)
    buf_set_keymap('n', 'gr', '<cmd>lua vim.lsp.buf.references()<CR>', opts)
    buf_set_keymap('n', '[d', '<cmd>lua vim.diagnostic.goto_prev()<CR>', opts)
    buf_set_keymap('n', ']d', '<cmd>lua vim.diagnostic.goto_next()<CR>', opts)
    buf_set_keymap('n', '<space>q', '<cmd>lua vim.diagnostic.setloclist()<CR>', opts)
    buf_set_keymap("n", "<space>ff", "<cmd>lua vim.lsp.buf.format()<CR>", opts)
end

local function shallow_copy(table)
    local copy = {}
    for k, v in pairs(table) do copy[k] = v end
    return copy
end

-- Merges rhs into lhs
local function merge(lhs, rhs)
    local lhs_copy = shallow_copy(lhs)
    for k, v in pairs(rhs) do lhs_copy[k] = v end
    return lhs_copy
end

local default_setup = {
    on_attach = on_attach,
    flags = {
        debounce_text_changes = 150,
    }
}

--Enable (broadcasting) snippet capability for completion
local capabilities = vim.lsp.protocol.make_client_capabilities()
capabilities.textDocument.completion.completionItem.snippetSupport = true

local sdk_path = tostring(vim.fn.getenv("OBMC_SDK_PATH"))

local server_specific_configuration = {
    yamlls = {
        settings = {
            yaml = {
                schemas = {
                    ["https://raw.githubusercontent.com/instrumenta/kubernetes-json-schema/master/v1.18.0-standalone-strict/all.json"] =
                    "/*.k8s.yaml",
                },
            },
        }
    },
    cssls = {
        capabilities = capabilities,
    },
    html = {
        capabilities = capabilities,
    },
    lua_ls = {
        settings = {
            Lua = {
                diagnostics = { globals = { 'vim' }
                }
            }
        }
    },
    clangd = {
        cmd = {
            "clangd",
            "--query-driver=" ..
            sdk_path .. "/sysroots/x86_64-oesdk-linux/usr/bin/arm-openbmc-linux-gnueabi/arm-openbmc-linux-gnueabi-g++"
        }
    }
}

local function get_configuration(lsp)
    return merge(default_setup, server_specific_configuration[lsp] or {})
end

-- Use a loop to conveniently call 'setup' on multiple servers and
-- map buffer local keybindings when the language server attaches
for _, lsp in ipairs(servers) do vim.lsp.config[lsp] = get_configuration(lsp) end

vim.diagnostic.config({
    virtual_text = true,
    float = {
        source = 'always',
        focusable = true,
        focus = false,
    },
    signs = {
        text = {
            [vim.diagnostic.severity.ERROR] = "",
            [vim.diagnostic.severity.WARN] = "",
            [vim.diagnostic.severity.INFO] = "",
            [vim.diagnostic.severity.HINT] = ""
        }
    }
})

local format_group = vim.api.nvim_create_augroup("__aditya__format_group", { clear = true })
local notes = { "*/notes", "*/note" }

vim.api.nvim_create_autocmd("BufEnter", {
    group = format_group,
    pattern = { "*.json" },
    callback = function()
        vim.cmd("set filetype=jsonc")
    end
})

vim.api.nvim_create_autocmd("BufEnter", {
    group = format_group,
    pattern = notes,
    callback = function()
        vim.cmd("set filetype=markdown")
    end
})

vim.api.nvim_create_autocmd("TermOpen", {
    group = format_group,
    callback = function()
        vim.cmd("setlocal nonu nornu")
    end
})

vim.api.nvim_create_autocmd("FileType", {
    group = format_group,
    pattern = "markdown",
    callback = function()
        vim.opt_local.textwidth = 80
        vim.opt_local.formatoptions:append("t")
    end
})

vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
    group = format_group,
    pattern = "*.txt",
    callback = function()
        vim.cmd("nmap <CR> :wq <CR>")
    end
})

vim.api.nvim_create_autocmd("BufWritePre", {
    group = format_group,
    pattern = "*",
    callback = function()
        vim.cmd([[%s/\s\+$//e]])
    end
})

vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
    group = format_group,
    pattern = ".zshrc",
    callback = function()
        vim.cmd("set filetype=bash")
    end
})

vim.api.nvim_create_autocmd({ "BufRead", "BufNewFile" }, {
    group = format_group,
    pattern = "*.html",
    callback = function()
        vim.cmd("set noexpandtab")
    end
})

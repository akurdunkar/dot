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

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [String[]]
    $Args
)

if (Test-Path -Path '.venv\Scripts\python.exe') {
    & '.venv\Scripts\python.exe' -m aries.cli @Args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m aries.cli @Args
} else {
    Write-Error 'Python interpreter not found. Install Python 3.11-3.13 and/or activate the project virtual environment.'
    exit 1
}

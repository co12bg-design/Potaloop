# PortaLoop - laptop lending and exchange tracker.
# Requiere Windows PowerShell 5.1 o PowerShell 7.
$ErrorActionPreference = 'Stop'
$dataFile = Join-Path $PSScriptRoot 'prestamos.json'

function Load-State {
    if (Test-Path -LiteralPath $dataFile) {
        try { $s = Get-Content -LiteralPath $dataFile -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { Write-Host "No se pudo leer prestamos.json: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
        return [pscustomobject]@{
            equipment = @($s.equipment); borrowers = @($s.borrowers); loans = @($s.loans)
            nextId = [int]$s.nextId
        }
    }
    return [pscustomobject]@{ equipment = @(); borrowers = @(); loans = @(); nextId = 1 }
}

$script:state = Load-State
function Save-State {
    $state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $dataFile -Encoding UTF8
}
function Test-ImageFile([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $extension = [IO.Path]::GetExtension($path).ToLowerInvariant()
    if ($extension -notin @('.jpg', '.jpeg', '.png')) { return $false }
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($path)
        if ($stream.Length -lt 8) { return $false }
        $header = [byte[]]::new(8)
        [void]$stream.Read($header, 0, 8)
        $isPng = $header[0] -eq 137 -and $header[1] -eq 80 -and $header[2] -eq 78 -and $header[3] -eq 71 -and $header[4] -eq 13 -and $header[5] -eq 10 -and $header[6] -eq 26 -and $header[7] -eq 10
        $isJpeg = $header[0] -eq 255 -and $header[1] -eq 216 -and $header[2] -eq 255
        return ($isPng -or $isJpeg)
    } catch { return $false }
    finally { if ($null -ne $stream) { $stream.Dispose() } }
}
function Get-PhotoEvidence([int]$loanId) {
    Write-Host 'Antes de entregar el portatil, toma una foto con el equipo visible.' -ForegroundColor Cyan
    try { Start-Process 'microsoft.windows.camera:' -ErrorAction Stop }
    catch { Write-Host 'No se pudo abrir Camara. Toma la foto con la app de tu equipo y continua con su ruta.' -ForegroundColor Yellow }
    $path = (Read-Host 'Ruta completa de la foto JPG o PNG (Enter cancela el prestamo)').Trim().Trim('"')
    if (-not $path) { Write-Host 'Prestamo cancelado: la foto es obligatoria.' -ForegroundColor Yellow; return $null }
    if (-not (Test-ImageFile $path)) { Write-Host 'Archivo invalido. Selecciona una imagen JPG o PNG real.' -ForegroundColor Yellow; return $null }
    $extension = [IO.Path]::GetExtension($path).ToLowerInvariant()
    $evidenceDir = Join-Path $PSScriptRoot 'evidencias'
    if (-not (Test-Path -LiteralPath $evidenceDir)) { [void](New-Item -ItemType Directory -Path $evidenceDir) }
    $destination = Join-Path $evidenceDir ("prestamo-{0}{1}" -f $loanId, $extension)
    try { Copy-Item -LiteralPath $path -Destination $destination -ErrorAction Stop }
    catch { Write-Host "No se pudo guardar la foto: $($_.Exception.Message)" -ForegroundColor Red; return $null }
    return (Join-Path 'evidencias' ("prestamo-{0}{1}" -f $loanId, $extension))
}
function Read-Date([string]$prompt, [bool]$defaultToday = $false) {
    $value = (Read-Host $prompt).Trim()
    if (-not $value -and $defaultToday) { return (Get-Date).Date }
    $parsed = [datetime]::MinValue
    $ok = [datetime]::TryParseExact($value, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$parsed)
    if (-not $ok) { Write-Host 'Fecha invalida; usa AAAA-MM-DD.' -ForegroundColor Yellow; return $null }
    return $parsed.Date
}
function Add-Equipment {
    $code = (Read-Host 'Codigo o placa').Trim().ToUpperInvariant()
    $description = (Read-Host 'Descripcion (marca/modelo)').Trim()
    if ($code -notmatch '^[A-Z0-9][A-Z0-9-]{1,19}$') { Write-Host 'Codigo invalido: usa 2-20 letras, numeros o guiones.'; return }
    if ($description.Length -lt 2 -or $description.Length -gt 80) { Write-Host 'La descripcion debe tener entre 2 y 80 caracteres.'; return }
    if (@($state.equipment | Where-Object code -eq $code).Count) { Write-Host 'Ese codigo ya existe.'; return }
    $state.equipment = @($state.equipment) + @([pscustomobject]@{ code=$code; description=$description; active=$true })
    Save-State; Write-Host 'Portatil registrado.' -ForegroundColor Green
}
function Add-Borrower {
    $doc = (Read-Host 'Documento de identidad').Trim()
    $name = (Read-Host 'Nombre completo').Trim()
    $contact = (Read-Host 'Contacto (opcional)').Trim()
    if ($doc -notmatch '^[\p{L}0-9][\p{L}0-9.-]{2,24}$') { Write-Host 'Documento invalido: usa 3-25 letras, numeros, punto o guion.'; return }
    if ($name -notmatch '^[\p{L}][\p{L}\p{M} .''-]{1,79}$') { Write-Host 'Nombre invalido: usa 2-80 letras, espacios, apostrofe, punto o guion.'; return }
    if ($contact -and $contact -notmatch '^(\+?[0-9][0-9 ()-]{5,19}|[^\s@]+@[^\s@]+\.[^\s@]+)$') { Write-Host 'Contacto invalido: escribe un telefono o correo electronico.'; return }
    if (@($state.borrowers | Where-Object document -eq $doc).Count) { Write-Host 'Ese documento ya esta registrado.'; return }
    $state.borrowers = @($state.borrowers) + @([pscustomobject]@{ document=$doc; name=$name; contact=$contact })
    Save-State; Write-Host 'Persona registrada.' -ForegroundColor Green
}
function Get-Pending { @($state.loans | Where-Object { -not $_.returnDate }) }
function Show-Available {
    $available = @($state.equipment | Where-Object {
        $code = $_.code
        $_.active -and -not (@(Get-Pending | Where-Object equipmentCode -eq $code).Count)
    })
    if (-not $available.Count) { Write-Host 'No hay portatiles disponibles.'; return }
    $available | ForEach-Object { Write-Host "$($_.code) - $($_.description)" }
}
function Show-Pending {
    $pending = @(Get-Pending)
    if (-not $pending.Count) { Write-Host 'No hay prestamos pendientes.'; return }
    $today = (Get-Date).Date
    foreach ($loan in $pending) {
        $status = if ([datetime]$loan.dueDate -lt $today) { 'VENCIDO' } else { 'vigente' }
        Write-Host "#$($loan.id) | $($loan.equipmentCode) ($($loan.description)) | $($loan.borrowerName) [$($loan.document)] | entrega $($loan.loanDate) | vence $($loan.dueDate) | $status | $($loan.notes)"
    }
}
function New-Loan {
    $code = (Read-Host 'Codigo del portatil').Trim().ToUpperInvariant()
    $equipment = $state.equipment | Where-Object { $_.code -eq $code -and $_.active } | Select-Object -First 1
    if (-not $equipment) { Write-Host 'No se encontro un portatil activo con ese codigo.'; return }
    if (@(Get-Pending | Where-Object equipmentCode -eq $code).Count) { Write-Host 'Ese portatil ya tiene un prestamo pendiente.'; return }
    $doc = (Read-Host 'Documento de quien recibe').Trim()
    $borrower = $state.borrowers | Where-Object document -eq $doc | Select-Object -First 1
    if (-not $borrower) { Write-Host 'Persona no registrada; usa primero la opcion 2.'; return }
    if (@(Get-Pending | Where-Object document -eq $doc).Count) {
        Write-Host "Prestamo bloqueado: $($borrower.name) ya tiene un portatil pendiente de devolucion." -ForegroundColor Red
        return
    }
    $loanDate = Read-Date "Fecha de entrega [Enter = $(Get-Date -Format yyyy-MM-dd)]" $true
    if ($null -eq $loanDate) { return }
    if ($loanDate -gt (Get-Date).Date) { Write-Host 'La fecha de entrega no puede estar en el futuro.'; return }
    $dueDate = Read-Date 'Fecha limite de devolucion (AAAA-MM-DD)'
    if ($null -eq $dueDate) { return }
    if ($dueDate -lt $loanDate) { Write-Host 'La fecha limite no puede ser anterior a la entrega.'; return }
    $notes = (Read-Host 'Observaciones o accesorios entregados (opcional)').Trim()
    $photoPath = Get-PhotoEvidence $state.nextId
    if (-not $photoPath) { return }
    $loan = [pscustomobject]@{ id=$state.nextId; equipmentCode=$code; description=$equipment.description; document=$doc; borrowerName=$borrower.name; loanDate=$loanDate.ToString('yyyy-MM-dd'); dueDate=$dueDate.ToString('yyyy-MM-dd'); returnDate=$null; notes=$notes; photoPath=$photoPath }
    $state.loans = @($state.loans) + @($loan); $state.nextId++
    Save-State; Write-Host 'Prestamo registrado.' -ForegroundColor Green
}
function Return-Equipment {
    Show-Pending
    $rawId = (Read-Host 'Numero de prestamo a devolver (Enter cancela)').Trim()
    if (-not $rawId) { return }
    $id = 0
    if (-not [int]::TryParse($rawId, [ref]$id)) { Write-Host 'Numero invalido.'; return }
    $loan = Get-Pending | Where-Object id -eq $id | Select-Object -First 1
    if (-not $loan) { Write-Host 'No existe ese prestamo pendiente.'; return }
    $returnDate = Read-Date "Fecha de devolucion [Enter = $(Get-Date -Format yyyy-MM-dd)]" $true
    if ($null -eq $returnDate) { return }
    if ($returnDate -lt [datetime]$loan.loanDate) { Write-Host 'La devolucion no puede ser anterior a la entrega.'; return }
    $loan.returnDate = $returnDate.ToString('yyyy-MM-dd')
    Save-State; Write-Host 'Devolucion registrada; el portatil esta disponible.' -ForegroundColor Green
}
function Show-History {
    $items = @($state.loans | Sort-Object { [int]$_.id } -Descending | Select-Object -First 30)
    if (-not $items.Count) { Write-Host 'Todavia no hay prestamos.'; return }
    foreach ($loan in $items) {
        $returned = if ($loan.returnDate) { $loan.returnDate } else { 'pendiente' }
        Write-Host "$($loan.equipmentCode) | $($loan.borrowerName) | $($loan.loanDate) -> $($loan.dueDate) | devolucion: $returned | foto: $($loan.photoPath) | $($loan.notes)"
    }
}

try {
    while ($true) {
        Write-Host "`n=== PORTALOOP | LAPTOP LENDING & EXCHANGE ===" -ForegroundColor Cyan
        Write-Host '1. Registrar portatil     2. Registrar persona'
        Write-Host '3. Registrar prestamo     4. Ver pendientes y vencidos'
        Write-Host '5. Registrar devolucion   6. Ver disponibles'
        Write-Host '7. Ver historial          0. Salir'
        $choice = (Read-Host 'Selecciona una opcion').Trim()
        switch ($choice) {
            '1' { Add-Equipment }
            '2' { Add-Borrower }
            '3' { New-Loan }
            '4' { Show-Pending }
            '5' { Return-Equipment }
            '6' { Show-Available }
            '7' { Show-History }
            '0' { Save-State; Write-Host 'Datos guardados. Hasta luego.'; break }
            default { Write-Host 'Opcion invalida.' -ForegroundColor Yellow }
        }
        if ($choice -eq '0') { break }
    }
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'El archivo de datos se conserva; verifica permisos y contenido.'
}

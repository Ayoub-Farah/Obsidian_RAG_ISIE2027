param([switch]$ProjectOnly,[int]$Mode=-1,[int]$Nodes=3,[int]$NodeBase=0,[int]$LocalNodes=1,[int]$DataBytes=6,[int]$RefBytes=2,[int]$RunCycles=128)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$action=if($ProjectOnly){'project'}else{'build'}
$argsList=@((Join-Path $PSScriptRoot 'vivado.py'),$action)
if($Mode -ge 0){$argsList+=@($Mode,$Nodes,$NodeBase,$LocalNodes,$DataBytes,$RefBytes,$RunCycles)}
elseif($Nodes -ne 3 -or $NodeBase -ne 0 -or $LocalNodes -ne 1 -or $DataBytes -ne 6 -or $RefBytes -ne 2 -or $RunCycles -ne 128){throw 'Spécifier -Mode quand le mapping, les tailles ou la durée sont modifiés.'}
& py -3 @argsList
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}

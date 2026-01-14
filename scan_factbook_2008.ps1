$folder = "C:\Users\Bryan\Desktop\county-map-data\Raw data\factbook-2008\rankorder"
$results = @()
Get-ChildItem -Path $folder -Filter '*rank.html' | ForEach-Object {
    $file = $_.Name
    $content = Get-Content $_.FullName -Raw
    $codeMatches = [regex]::Matches($content, 'geos/([a-z]{2})\.html')
    $codes = $codeMatches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    $titleMatch = [regex]::Match($content, '<title>CIA - The World Factbook -- Rank Order - ([^<]*)</title>')
    $title = if ($titleMatch.Success) { $titleMatch.Groups[1].Value } else { 'Unknown' }
    $results += [PSCustomObject]@{
        File = $file
        FieldID = $file -replace 'rank\.html', ''
        Title = $title
        CountryCount = $codes.Count
    }
}
$results | Sort-Object -Property CountryCount -Descending | Format-Table -AutoSize
Write-Host ""
Write-Host "--- SUMMARY ---"
Write-Host "Total rank files: $($results.Count)"
Write-Host "Max countries in any file: $(($results | Measure-Object -Property CountryCount -Maximum).Maximum)"
Write-Host "Min countries in any file: $(($results | Measure-Object -Property CountryCount -Minimum).Minimum)"
Write-Host "Average countries per file: $([math]::Round(($results | Measure-Object -Property CountryCount -Average).Average, 1))"

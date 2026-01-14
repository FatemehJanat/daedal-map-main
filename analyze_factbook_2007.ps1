$rankFolder = 'C:\Users\Bryan\Desktop\county-map-data\Raw data\factbook-2007\rankorder'
$files = Get-ChildItem -Path $rankFolder -Filter '*rank.html'
$results = @()

foreach ($file in $files) {
    $content = Get-Content -Path $file.FullName -Raw

    # Extract title - look for 'Rank Order - XXX' pattern
    $titleMatch = [regex]::Match($content, '<title>.*?Rank Order - ([^<]+)</title>')
    $title = if ($titleMatch.Success) { $titleMatch.Groups[1].Value.Trim() } else { 'Unknown' }

    # Also try to get from the body header
    if ($title -eq 'Unknown' -or $title -eq '') {
        $headerMatch = [regex]::Match($content, 'Rank Order - ([^<]+)</font>')
        if ($headerMatch.Success) { $title = $headerMatch.Groups[1].Value.Trim() }
    }

    # Count unique 2-letter country codes from geos/XX.html pattern
    $geoMatches = [regex]::Matches($content, 'geos/([a-z]{2})\.html')
    $countryCodes = @{}
    foreach ($match in $geoMatches) {
        $code = $match.Groups[1].Value
        $countryCodes[$code] = $true
    }

    $fileId = [regex]::Match($file.Name, '(\d+)rank\.html').Groups[1].Value

    $results += [PSCustomObject]@{
        FileID = $fileId
        FileName = $file.Name
        Title = $title
        CountryCount = $countryCodes.Count
    }
}

# Sort by FileID
$results = $results | Sort-Object { [int]$_.FileID }

Write-Host '=== CIA Factbook 2007 Rank Files Analysis ===' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Total rank files found:' $files.Count
Write-Host 'Max countries in any file:' ($results | Measure-Object -Property CountryCount -Maximum).Maximum
Write-Host ''
Write-Host '=== All Metrics with Country Counts ===' -ForegroundColor Cyan
Write-Host ''
foreach ($r in $results) {
    Write-Host ('{0,-12} {1,-60} Countries: {2}' -f $r.FileID, $r.Title, $r.CountryCount)
}

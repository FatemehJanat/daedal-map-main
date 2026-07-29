options(repos = c(CRAN = "https://cloud.r-project.org"))
options(java.parameters = "-Xmx6G")

pkgs <- c("data.table", "sf", "r5r")
for (p in pkgs) {
  if (!requireNamespace(p, quietly = TRUE)) install.packages(p)
}

library(data.table)
library(sf)

repo_dir <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"
network_root <- file.path(repo_dir, "static", "data", "r5r_lake_network")
dir.create(network_root, recursive = TRUE, showWarnings = FALSE)

library(r5r)

r5_version <- "6.4.0"

osm_sources <- list(
  list(
    name = "norcal",
    url = "https://download.geofabrik.de/north-america/us/california/norcal-latest.osm.pbf"
  ),
  list(
    name = "california",
    url = "https://download.geofabrik.de/north-america/us/california-latest.osm.pbf"
  )
)

r5 <- NULL
network_dir <- NULL
used_source <- NULL

for (src in osm_sources) {
  candidate_dir <- file.path(network_root, src$name)
  dir.create(candidate_dir, recursive = TRUE, showWarnings = FALSE)

  pbf_path <- file.path(candidate_dir, basename(src$url))
  if (!file.exists(pbf_path) || file.info(pbf_path)$size < 100000000) {
    download.file(src$url, destfile = pbf_path, mode = "wb", quiet = FALSE)
  }
  if (!file.exists(pbf_path)) {
    cat("SOURCE_DOWNLOAD_FAILED:", src$name, "\n")
    next
  }

  cat("TRY_SOURCE:", src$name, "\n")
  r5_try <- try(
    setup_r5(
      data_path = candidate_dir,
      version = r5_version,
      verbose = TRUE,
      overwrite = TRUE
    ),
    silent = TRUE
  )

  if (!inherits(r5_try, "try-error")) {
    r5 <- r5_try
    network_dir <- candidate_dir
    used_source <- src$name
    break
  }

  cat("SOURCE_SETUP_FAILED:", src$name, "\n")
  cat(as.character(r5_try), "\n")
}

if (is.null(r5)) {
  stop("Failed to build R5 network from all configured official OSM sources.")
}

origins_sf <- st_read(file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
origins_sf <- st_transform(origins_sf, 4326)
origins_pts <- st_point_on_surface(origins_sf)

origins <- data.table(
  id = as.character(origins_pts$GEOID),
  lon = st_coordinates(origins_pts)[, 1],
  lat = st_coordinates(origins_pts)[, 2]
)

shelters_sf <- st_read(file.path(repo_dir, "static", "data", "nss_lake_county_facilities.geojson"), quiet = TRUE)
shelters_sf <- st_transform(shelters_sf, 4326)

shelters <- data.table(
  id = as.character(shelters_sf$shelter_id),
  lon = st_coordinates(shelters_sf)[, 1],
  lat = st_coordinates(shelters_sf)[, 2],
  opportunities = 1
)

acc <- accessibility(
  r5r_core = r5,
  origins = origins,
  destinations = shelters,
  mode = "CAR",
  opportunities_colname = "opportunities",
  cutoffs = 30,
  verbose = TRUE,
  progress = FALSE
)

stop_r5(r5)

setDT(acc)
setnames(acc, old = c("id", "opportunities", "cutoff"), new = c("GEOID", "shelters_within_30min_car", "cutoff_min"), skip_absent = TRUE)

out_csv <- file.path(repo_dir, "static", "data", "lake_county_shelter_access_car30_r5r.csv")
fwrite(acc, out_csv)

tracts <- st_read(file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tracts_dt <- as.data.table(st_drop_geometry(tracts))[, .(GEOID)]
acc_join <- merge(tracts_dt, acc[, .(GEOID, shelters_within_30min_car)], by = "GEOID", all.x = TRUE)
tracts$shelters_within_30min_car <- acc_join$shelters_within_30min_car[match(tracts$GEOID, acc_join$GEOID)]

out_geojson <- file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri_access.geojson")
st_write(tracts, out_geojson, delete_dsn = TRUE, quiet = TRUE)

cat("OUTPUT_CSV:", out_csv, "\n")
cat("OUTPUT_GEOJSON:", out_geojson, "\n")
cat("TRACTS:", nrow(origins), "\n")
cat("SHELTERS:", nrow(shelters), "\n")
cat("ACCESS_ROWS:", nrow(acc), "\n")
cat("ACCESS_SUMMARY_MIN:", min(acc$shelters_within_30min_car, na.rm = TRUE), "\n")
cat("ACCESS_SUMMARY_MAX:", max(acc$shelters_within_30min_car, na.rm = TRUE), "\n")
cat("R5_VERSION:", r5_version, "\n")
cat("OSM_SOURCE:", used_source, "\n")
cat("NETWORK_DIR:", network_dir, "\n")

options(repos = c(CRAN = "https://cloud.r-project.org"))

pkgs <- c("data.table", "sf", "osrm")
for (p in pkgs) {
  if (!requireNamespace(p, quietly = TRUE)) install.packages(p)
}

library(data.table)
library(sf)
library(osrm)

repo_dir <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"

tracts_path <- file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri.geojson")
shelters_path <- file.path(repo_dir, "static", "data", "nss_lake_county_facilities.geojson")

tracts <- st_read(tracts_path, quiet = TRUE)
tracts <- st_transform(tracts, 4326)

# Representative points inside each tract polygon.
tract_pts <- st_point_on_surface(tracts)

shelters <- st_read(shelters_path, quiet = TRUE)
shelters <- st_transform(shelters, 4326)

origins <- data.table(
  id = as.character(tract_pts$GEOID),
  lon = st_coordinates(tract_pts)[, 1],
  lat = st_coordinates(tract_pts)[, 2]
)

destinations <- data.table(
  id = as.character(shelters$shelter_id),
  lon = st_coordinates(shelters)[, 1],
  lat = st_coordinates(shelters)[, 2]
)

if (nrow(origins) == 0 || nrow(destinations) == 0) {
  stop("Origins or destinations are empty; cannot compute accessibility.")
}

options(osrm.server = "https://router.project-osrm.org/", osrm.profile = "car")

route_duration_min <- function(lon1, lat1, lon2, lat2, max_retries = 2L) {
  src <- st_as_sf(data.frame(id = "src", lon = lon1, lat = lat1), coords = c("lon", "lat"), crs = 4326)
  dst <- st_as_sf(data.frame(id = "dst", lon = lon2, lat = lat2), coords = c("lon", "lat"), crs = 4326)

  for (attempt in seq_len(max_retries)) {
    res <- tryCatch({
      setTimeLimit(elapsed = 8, transient = TRUE)
      osrmRoute(src = src, dst = dst, overview = FALSE)
    }, error = function(e) {
      NA_real_
    }, finally = {
      setTimeLimit(cpu = Inf, elapsed = Inf, transient = FALSE)
    })

    if (length(res) >= 1 && is.finite(res[1])) {
      return(as.numeric(res[1]))
    }
    Sys.sleep(0.15 * attempt)
  }

  return(NA_real_)
}

thresholds <- c(30L, 45L, 60L)
count_matrix <- matrix(0L, nrow = nrow(origins), ncol = length(thresholds))
colnames(count_matrix) <- paste0("shelters_within_", thresholds, "min_car")

for (i in seq_len(nrow(origins))) {
  for (j in seq_len(nrow(destinations))) {
    dur_min <- route_duration_min(
      lon1 = origins$lon[i],
      lat1 = origins$lat[i],
      lon2 = destinations$lon[j],
      lat2 = destinations$lat[j],
      max_retries = 3L
    )
    if (!is.finite(dur_min)) {
      next
    }
    for (k in seq_along(thresholds)) {
      if (dur_min <= thresholds[k]) {
        count_matrix[i, k] <- count_matrix[i, k] + 1L
      }
    }
    Sys.sleep(0.02)
  }
  cat("PROGRESS_ORIGIN", i, "OF", nrow(origins), "COUNTS", paste(count_matrix[i, ], collapse = ","), "\n")
}

acc <- data.table(
  GEOID = origins$id,
  shelters_within_30min_car = as.integer(count_matrix[, "shelters_within_30min_car"]),
  shelters_within_45min_car = as.integer(count_matrix[, "shelters_within_45min_car"]),
  shelters_within_60min_car = as.integer(count_matrix[, "shelters_within_60min_car"]),
  cutoff_min = 30L,
  method = "osrm_car"
)

out_csv <- file.path(repo_dir, "static", "data", "lake_county_shelter_access_car30_r5r.csv")
fwrite(acc, out_csv)

tracts$shelters_within_30min_car <- acc$shelters_within_30min_car[match(tracts$GEOID, acc$GEOID)]
tracts$shelters_within_45min_car <- acc$shelters_within_45min_car[match(tracts$GEOID, acc$GEOID)]
tracts$shelters_within_60min_car <- acc$shelters_within_60min_car[match(tracts$GEOID, acc$GEOID)]
tracts$access_method <- "osrm_car"
tracts$access_cutoff_min <- 30L

out_geojson <- file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri_access.geojson")
st_write(tracts, out_geojson, delete_dsn = TRUE, quiet = TRUE)

cat("OUTPUT_CSV:", out_csv, "\n")
cat("OUTPUT_GEOJSON:", out_geojson, "\n")
cat("TRACTS:", nrow(origins), "\n")
cat("SHELTERS:", nrow(destinations), "\n")
cat("ACCESS_ROWS:", nrow(acc), "\n")
cat("ACCESS_SUMMARY_MIN:", min(acc$shelters_within_30min_car, na.rm = TRUE), "\n")
cat("ACCESS_SUMMARY_MAX:", max(acc$shelters_within_30min_car, na.rm = TRUE), "\n")
cat("METHOD:", "osrm_car", "\n")
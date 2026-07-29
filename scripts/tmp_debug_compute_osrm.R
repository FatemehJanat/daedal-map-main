library(sf)
library(data.table)
library(osrm)

repo_dir <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"
tracts <- st_read(file.path(repo_dir, "static", "data", "tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tracts <- st_transform(tracts, 4326)
tract_pts <- st_point_on_surface(tracts)

shelters <- st_read(file.path(repo_dir, "static", "data", "nss_lake_county_facilities.geojson"), quiet = TRUE)
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

options(osrm.server = "https://router.project-osrm.org/", osrm.profile = "car")

route_duration_min <- function(lon1, lat1, lon2, lat2, max_retries = 2L) {
  src <- st_as_sf(data.frame(id = "src", lon = lon1, lat = lat1), coords = c("lon", "lat"), crs = 4326)
  dst <- st_as_sf(data.frame(id = "dst", lon = lon2, lat = lat2), coords = c("lon", "lat"), crs = 4326)

  for (attempt in seq_len(max_retries)) {
    cat("attempt", attempt, "\n")
    res <- tryCatch({
      setTimeLimit(elapsed = 8, transient = TRUE)
      osrmRoute(src = src, dst = dst, overview = FALSE)
    }, error = function(e) {
      cat("error", conditionMessage(e), "\n")
      NA_real_
    }, finally = {
      setTimeLimit(cpu = Inf, elapsed = Inf, transient = FALSE)
    })

    print(res)
    if (length(res) >= 1 && is.finite(res[1])) {
      return(as.numeric(res[1]))
    }
    Sys.sleep(0.15 * attempt)
  }

  return(NA_real_)
}

for (j in 1:3) {
  cat("dest", j, "\n")
  d <- route_duration_min(origins$lon[1], origins$lat[1], destinations$lon[j], destinations$lat[j])
  cat("dur", d, "\n")
}

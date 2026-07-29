library(sf)
library(data.table)
library(osrm)

repo <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"

tracts <- st_read(file.path(repo, "static/data/tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tracts <- st_transform(tracts, 4326)
tract_pts <- st_point_on_surface(tracts)

shelters <- st_read(file.path(repo, "static/data/nss_lake_county_facilities.geojson"), quiet = TRUE)
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

origins_sf <- st_as_sf(origins, coords = c("lon", "lat"), crs = 4326, remove = FALSE)
destinations_sf <- st_as_sf(destinations, coords = c("lon", "lat"), crs = 4326, remove = FALSE)

res <- osrmTable(src = origins_sf, dst = destinations_sf)
cat("durations class:", class(res$durations), "\n")
cat("durations dim:", dim(res$durations), "\n")

m <- as.matrix(res$durations)
cat("matrix dim:", nrow(m), ncol(m), "\n")
cat("global min:", min(m, na.rm = TRUE), "global max:", max(m, na.rm = TRUE), "\n")

mins <- apply(m, 1, min, na.rm = TRUE)
maxs <- apply(m, 1, max, na.rm = TRUE)
cat("origin-min range:", min(mins), max(mins), "\n")
cat("origin-max range:", min(maxs), max(maxs), "\n")

counts30 <- rowSums(is.finite(m) & m <= 30, na.rm = TRUE)
cat("count<=30 min range:", min(counts30), max(counts30), "\n")
print(data.frame(GEOID = origins$id, min_min = mins, max_min = maxs, count_30 = counts30))

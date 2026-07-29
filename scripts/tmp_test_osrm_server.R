library(sf)
library(data.table)
library(osrm)

repo <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"
tracts <- st_read(file.path(repo, "static/data/tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tracts <- st_transform(tracts, 4326)
tract_pts <- st_point_on_surface(tracts)
shelters <- st_read(file.path(repo, "static/data/nss_lake_county_facilities.geojson"), quiet = TRUE)
shelters <- st_transform(shelters, 4326)

src <- data.frame(id = "o1", lon = st_coordinates(tract_pts)[1,1], lat = st_coordinates(tract_pts)[1,2])
dst <- data.frame(id = "d1", lon = st_coordinates(shelters)[1,1], lat = st_coordinates(shelters)[1,2])

src_sf <- st_as_sf(src, coords = c("lon","lat"), crs = 4326, remove = FALSE)
dst_sf <- st_as_sf(dst, coords = c("lon","lat"), crs = 4326, remove = FALSE)

servers <- c("https://router.project-osrm.org/", "https://routing.openstreetmap.de/routed-car/")
for (s in servers) {
  options(osrm.server = s, osrm.profile = "car")
  cat("SERVER", s, "\n")
  t <- try(osrmTable(src = src_sf, dst = dst_sf), silent = TRUE)
  if (inherits(t, "try-error")) {
    cat("TABLE_ERROR\n")
  } else {
    print(t$durations)
  }
}

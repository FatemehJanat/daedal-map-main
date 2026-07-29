library(sf)
library(osrm)

repo <- "C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main"
tr <- st_read(file.path(repo, "static/data/tiger2020_lake_county_tracts_nri.geojson"), quiet = TRUE)
tr <- st_transform(tr, 4326)
trp <- st_point_on_surface(tr)
sh <- st_read(file.path(repo, "static/data/nss_lake_county_facilities.geojson"), quiet = TRUE)
sh <- st_transform(sh, 4326)

options(osrm.server = "https://router.project-osrm.org/", osrm.profile = "car")

src <- data.frame(id = "o1", lon = st_coordinates(trp)[1, 1], lat = st_coordinates(trp)[1, 2])
src <- st_as_sf(src, coords = c("lon", "lat"), crs = 4326)
for (j in 1:5) {
  dst <- data.frame(id = paste0("d", j), lon = st_coordinates(sh)[j, 1], lat = st_coordinates(sh)[j, 2])
  dst <- st_as_sf(dst, coords = c("lon", "lat"), crs = 4326)
  r <- osrmRoute(src = src, dst = dst, overview = FALSE)
  cat("j", j, "class", class(r), "value", r, "\n")
}

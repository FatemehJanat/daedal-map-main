library(httr)
library(jsonlite)

url <- "https://router.project-osrm.org/route/v1/driving/-122.863115,39.120886;-122.787000,39.050000?overview=false&alternatives=false&steps=false"
res <- GET(url, timeout(6))
cat("status", status_code(res), "\n")
txt <- content(res, as = "text", encoding = "UTF-8")
obj <- fromJSON(txt)
str(obj)
print(obj$code)
print(obj$routes)

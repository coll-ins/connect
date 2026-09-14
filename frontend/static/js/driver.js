let locationWatcher
let driverMap
let driverMarker
let passengerMarkers = new Map()
let routeLines = new Map()
let bookingRefreshTimer
let nearestPassengerDistance

async function loadDriverChoices() {
    const company = document.getElementById('company').value
    const res = await getDrivers(company)
    const select = document.getElementById('driver')
    select.innerHTML = '<option value="">Choose your driver profile</option>'
    if (res.ok) res.data.forEach(driver => {
        select.insertAdjacentHTML('beforeend', `<option value="${driver.id}">${driver.name} - ${driver.bus_number}</option>`)
    })
}

function startSharing() {
    const driverId = document.getElementById('driver').value
    const message = document.getElementById('message')
    if (!driverId) {
        message.textContent = 'Choose your driver profile first.'
        return
    }
    if (!navigator.geolocation) {
        message.textContent = 'This browser does not support location sharing.'
        return
    }
    if (locationWatcher) navigator.geolocation.clearWatch(locationWatcher)
    initializeDriverMap()
    loadAssignedPassengers(driverId)
    clearInterval(bookingRefreshTimer)
    bookingRefreshTimer = setInterval(() => loadAssignedPassengers(driverId), 5000)
    locationWatcher = navigator.geolocation.watchPosition(async position => {
        const { latitude, longitude } = position.coords
        const res = await updateDriverLocation(driverId, latitude, longitude)
        message.textContent = res.ok ? 'Location is being shared with passengers.' : 'Could not update location.'
        updateDriverMap(latitude, longitude)
        loadAssignedPassengers(driverId)
    }, () => {
        message.textContent = 'Please allow location access in your browser.'
    }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 15000 })
}

function initializeDriverMap() {
    const mapElement = document.getElementById('driver-map')
    if (!mapElement || !window.L || driverMap) return
    driverMap = L.map(mapElement).setView([-1.286389, 36.817223], 13)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(driverMap)
}

function updateDriverMap(latitude, longitude) {
    if (!driverMap) return
    if (!driverMarker) {
        driverMarker = L.marker([latitude, longitude]).addTo(driverMap).bindPopup('You are here')
    } else {
        driverMarker.setLatLng([latitude, longitude])
    }
    updateDriverSummary()
    fitDriverMap()
}

async function loadAssignedPassengers(driverId) {
    const res = await getDriverBookings(driverId)
    if (!res.ok || !driverMap) return
    const activeIds = new Set(res.data.map(booking => booking.id))
    passengerMarkers.forEach((marker, bookingId) => {
        if (!activeIds.has(bookingId)) {
            driverMap.removeLayer(marker)
            passengerMarkers.delete(bookingId)
            if (routeLines.has(bookingId)) driverMap.removeLayer(routeLines.get(bookingId))
            routeLines.delete(bookingId)
        }
    })
    res.data.forEach(booking => {
        if (booking.passenger_latitude === null || booking.passenger_longitude === null) return
        const point = [Number(booking.passenger_latitude), Number(booking.passenger_longitude)]
        let marker = passengerMarkers.get(booking.id)
        if (!marker) {
            marker = L.circleMarker(point, { radius: 9, color: '#c27a13', fillColor: '#fbbf24', fillOpacity: 1, weight: 3 })
                .addTo(driverMap)
                .bindPopup(`Passenger ${booking.booking_number}`)
            passengerMarkers.set(booking.id, marker)
        } else {
            marker.setLatLng(point)
        }
        if (driverMarker) {
            let line = routeLines.get(booking.id)
            if (!line) {
                line = L.polyline([driverMarker.getLatLng(), point], { color: '#176b45', weight: 4, opacity: .8, dashArray: '8 8' }).addTo(driverMap)
                routeLines.set(booking.id, line)
            } else {
                line.setLatLngs([driverMarker.getLatLng(), point])
            }
        }
    })
    document.getElementById('passenger-count').textContent = `${res.data.length} passenger${res.data.length === 1 ? '' : 's'}`
    fitDriverMap()
}

function updateDriverSummary() {
    if (!driverMarker || !passengerMarkers.size) return
    const driverPoint = driverMarker.getLatLng()
    nearestPassengerDistance = Math.min(...[...passengerMarkers.values()].map(marker => driverPoint.distanceTo(marker.getLatLng())))
    document.getElementById('driver-distance').textContent = `${(nearestPassengerDistance / 1000).toFixed(1)} km to nearest pickup`
}

function fitDriverMap() {
    if (!driverMap) return
    const layers = [driverMarker, ...passengerMarkers.values()].filter(Boolean)
    if (layers.length > 1) driverMap.fitBounds(L.featureGroup(layers).getBounds(), { padding: [48, 48] })
    else if (driverMarker) driverMap.setView(driverMarker.getLatLng(), 15)
}
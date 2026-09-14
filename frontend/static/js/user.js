// Passenger-side logic
const NEUTRAL_BUS_IMAGE = '../assets/neutral-transit.jpg'
const COMPANY_MARKS = {
    Supermetro: { className: 'supermetro', mark: 'SM' },
    CityShuttle: { className: 'cityshuttle', mark: 'CS' },
    Latema: { className: 'latema', mark: 'LT' },
}

// saves data between pages
function save(key, value) { localStorage.setItem(key, JSON.stringify(value)) }
function load(key) {
    try { return JSON.parse(localStorage.getItem(key)) } catch { return null }
}

function showError(id, msg) {
    const el = document.getElementById(id)
    if (el) el.textContent = msg
}

async function loadBookingSidebar() {
    const list = document.getElementById('sidebar-bookings')
    if (!list) return
    if (!load('user')) {
        list.innerHTML = '<p class="sidebar-empty">Sign in to see your bookings</p>'
        return
    }
    const res = await getMyBookings()
    if (!res.ok) {
        list.innerHTML = '<p class="sidebar-empty">Sign in again to load bookings</p>'
        return
    }
    const pending = res.data.filter(booking => booking.status === 'pending')
    const ongoing = res.data.filter(booking => booking.status === 'confirmed' && booking.driver_name)
    const confirmed = res.data.filter(booking => booking.status === 'confirmed' && !booking.driver_name)
    const previous = res.data.filter(booking => !['pending', 'confirmed'].includes(booking.status))
    list.innerHTML = ''
    const groups = [
        ['Pending confirmation', pending],
        ['Confirmed', confirmed],
        ['Ongoing', ongoing],
        ['Previous bookings', previous],
    ]
    groups.forEach(([title, bookings]) => {
        const heading = document.createElement('div')
        heading.className = 'sidebar-group-title'
        heading.textContent = title
        list.appendChild(heading)
        if (!bookings.length) {
            const empty = document.createElement('p')
            empty.className = 'sidebar-empty'
            empty.textContent = 'None yet'
            list.appendChild(empty)
        }
        bookings.forEach(booking => {
            const item = document.createElement('div')
            item.className = 'sidebar-booking'
            item.innerHTML = `<strong>${booking.booking_number}</strong><span>${booking.route_name || 'Trip'} · ${booking.seats} seat${booking.seats === 1 ? '' : 's'}</span><em>${booking.status}</em>`
            item.onclick = () => {
                save('current_booking', booking)
                window.location.href = booking.status === 'confirmed' && booking.driver_name ? 'trip.html' : 'booking.html'
            }
            list.appendChild(item)
        })
    })
}

// SIGNUP PAGE
async function handleSignup(e) {
    e.preventDefault()
    showError('error', '')
    const data = {
        username: document.getElementById('name').value,
        phone_number: document.getElementById('phone').value,
        location: document.getElementById('location').value,
        password: document.getElementById('password').value,
    }
    const res = await signup(data)
    if (res.ok) {
        save('user', res.data.user)
        window.location.href = 'companies.html'
    } else {
        const err = Object.values(res.data)[0]
        showError('error', Array.isArray(err) ? err[0] : err)
    }
}

// LOGIN PAGE
async function handleLogin(e) {
    e.preventDefault()
    showError('error', '')
    const data = {
        phone_number: document.getElementById('phone').value.trim(),
        password: document.getElementById('password').value,
    }
    const res = await login(data)
    if (res.ok) {
        save('user', res.data.user)
        if (res.data.user.is_admin) {
            window.location.href = '../admin/dashboard.html'
        } else {
            window.location.href = 'companies.html'
        }
    } else {
        showError('error', res.data.error)
    }
}

// COMPANIES PAGE
async function loadCompanies() {
    const res = await getCompanies()

    if (res.ok) {
        const list = document.getElementById('company-list')
        list.innerHTML = ''
        res.data.forEach(company => {
            const visual = COMPANY_MARKS[company.name] || { className: 'default', mark: company.name.slice(0, 2).toUpperCase() }
            const card = document.createElement('div')
            card.className = `card company-card company-${visual.className}`
            card.innerHTML = `
                <div class="company-card-image">
                    <img src="${NEUTRAL_BUS_IMAGE}" alt="Public transit bus serving ${company.name}">
                    <span class="company-mark" aria-hidden="true">${visual.mark}</span>
                </div>
                <div class="company-card-copy">
                <h3>${company.name}</h3>
                <p>${company.areas_served}</p>
                </div>
            `
            card.onclick = () => {
                save('selected_company', company)
                window.location.href = 'routes.html'
            }
            list.appendChild(card)
        })
    } else {
        list.innerHTML = '<p class="error-msg">Could not load companies. Please refresh.</p>'
    }
}

// ROUTES PAGE
async function loadRoutes() {
    const company = load('selected_company')
    if (!company) { window.location.href = 'companies.html'; return }

    document.getElementById('company-name').textContent = company.name
    const res = await getRoutes(company.id)

    if (res.ok) {
        const list = document.getElementById('route-list')
        list.innerHTML = ''
        res.data.forEach(route => {
            const card = document.createElement('div')
            card.className = 'card'
            card.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <h3>${route.name}</h3>
                    <span class="price">KSh ${route.price}</span>
                </div>
                <p style="margin-top:6px">${route.start_point} → ${route.end_point}</p>
            `
            card.onclick = () => {
                save('selected_route', route)
                window.location.href = 'booking.html'
            }
            list.appendChild(card)
        })
    }
}

// BOOKING PAGE
async function handleBooking(e) {
    e.preventDefault()
    showError('error', '')
    const route = load('selected_route')
    const user = load('user')

    if (!user) { window.location.href = 'index.html'; return }
    if (!route) { window.location.href = 'routes.html'; return }

    const data = {
        route_id: route.id,
        pickup_location: document.getElementById('pickup').value,
        seats: document.getElementById('seats').value,
    }

    const res = await createBooking(data)
    if (res.ok) {
        save('current_booking', res.data.booking)
        showBookingConfirmation(res.data.booking)
    } else {
        showError('error', res.data.error || 'Booking failed')
    }
}

function initializeTripPage() {
    const booking = load('current_booking')
    if (!booking) {
        window.location.href = 'companies.html'
        return
    }

    document.getElementById('trip-booking-number').textContent = booking.booking_number
    document.getElementById('trip-route').textContent = booking.route_name || 'Your selected route'
    document.getElementById('trip-pickup').textContent = booking.pickup_location
    document.getElementById('trip-seats').textContent = `${booking.seats || 1} seat${Number(booking.seats) === 1 ? '' : 's'}`
    document.getElementById('complete-trip-button').hidden = booking.status !== 'confirmed'
    loadBookingSidebar()
    initializeTripMap()
    if (booking.driver_name) showTripDriver(booking)
    startPassengerLocationTracking()
    refreshTripPage(booking.booking_number)
    window.tripRefreshTimer = setInterval(() => refreshTripPage(booking.booking_number), 5000)
}

function startPassengerLocationTracking() {
    if (!navigator.geolocation) return
    window.passengerLocationWatcher = navigator.geolocation.watchPosition(position => {
        const latitude = position.coords.latitude
        const longitude = position.coords.longitude
        const booking = load('current_booking')
        if (booking && booking.status === 'confirmed') {
            updatePassengerLocation(booking.id, latitude, longitude)
        }
        showUserLocation(latitude, longitude)
        checkPassengerArrival(latitude, longitude)
    }, () => {
        document.getElementById('trip-status-detail').textContent = 'Allow location access to detect arrival automatically.'
    }, { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 })
}

function checkPassengerArrival(latitude, longitude) {
    const booking = load('current_booking')
    if (!booking || booking.status !== 'confirmed' || !window.driverLocation || window.arrivalCompleting) return
    const distance = distanceInMeters(latitude, longitude, window.driverLocation.latitude, window.driverLocation.longitude)
    if (distance <= 100) completeTripOnArrival()
}

function distanceInMeters(latitudeOne, longitudeOne, latitudeTwo, longitudeTwo) {
    const earthRadius = 6371000
    const latitudeDelta = (latitudeTwo - latitudeOne) * Math.PI / 180
    const longitudeDelta = (longitudeTwo - longitudeOne) * Math.PI / 180
    const latitudeOneRadians = latitudeOne * Math.PI / 180
    const latitudeTwoRadians = latitudeTwo * Math.PI / 180
    const value = Math.sin(latitudeDelta / 2) ** 2
        + Math.cos(latitudeOneRadians) * Math.cos(latitudeTwoRadians) * Math.sin(longitudeDelta / 2) ** 2
    return 2 * earthRadius * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))
}

async function completeTripOnArrival() {
    const booking = load('current_booking')
    if (!booking) return
    window.arrivalCompleting = true
    document.getElementById('trip-status').textContent = 'You have arrived'
    document.getElementById('trip-status-detail').textContent = 'Closing your ride automatically.'
    const res = await completeBooking(booking.id)
    if (res.ok) {
        save('current_booking', res.data.booking)
        clearInterval(window.tripRefreshTimer)
        if (window.passengerLocationWatcher) navigator.geolocation.clearWatch(window.passengerLocationWatcher)
        document.getElementById('complete-trip-button').hidden = true
        document.getElementById('trip-status-detail').textContent = 'Ride completed and saved to Previous bookings.'
        loadBookingSidebar()
    } else {
        window.arrivalCompleting = false
        document.getElementById('trip-status-detail').textContent = 'You have arrived. Tap Complete trip to close the ride.'
    }
}

function toggleTripSidebar() {
    document.getElementById('trip-sidebar').classList.toggle('open')
    document.getElementById('trip-sidebar-backdrop').classList.toggle('open')
}

async function refreshTripPage(bookingNumber) {
    const res = await getMyBookings()
    if (!res.ok) return
    const booking = res.data.find(item => item.booking_number === bookingNumber)
    if (!booking) return
    save('current_booking', booking)
    if (booking.status === 'completed') {
        clearInterval(window.tripRefreshTimer)
        document.getElementById('trip-status').textContent = 'Trip completed'
        document.getElementById('trip-status-detail').textContent = 'This booking is now in Previous bookings.'
        return
    }
    document.getElementById('trip-status').textContent = booking.status === 'confirmed' ? 'Driver confirmed' : 'Finding your driver'
    document.getElementById('trip-status-detail').textContent = booking.status === 'confirmed' ? 'Your driver is on the way.' : 'We are matching you with a driver.'
    updatePassengerEta(booking)
    if (booking.driver_name) showTripDriver(booking)
}

function updatePassengerEta(booking) {
    const eta = document.getElementById('trip-eta')
    if (!eta) return
    if (booking.driver_latitude && booking.driver_longitude && booking.passenger_latitude && booking.passenger_longitude) {
        const distance = distanceInMeters(Number(booking.driver_latitude), Number(booking.driver_longitude), Number(booking.passenger_latitude), Number(booking.passenger_longitude))
        const minutes = Math.max(1, Math.ceil(distance / 500))
        eta.textContent = `${minutes} min to your pickup · ${(distance / 1000).toFixed(1)} km away`
    } else if (booking.stage_departure_minutes !== null && booking.stage_departure_minutes !== undefined) {
        eta.textContent = booking.stage_departure_minutes === 0
            ? 'Bus has left the stage · waiting for live location'
            : `Bus leaves the stage in ${booking.stage_departure_minutes} min`
    } else {
        eta.textContent = 'Waiting for the operator to set a departure time.'
    }
}

function showTripDriver(booking) {
    document.getElementById('driver-name').textContent = booking.driver_name
    document.getElementById('driver-phone').textContent = booking.driver_phone
    document.getElementById('driver-bus').textContent = `Bus ${booking.driver_bus}`
    document.getElementById('trip-driver-card').hidden = false
    if (booking.driver_latitude && booking.driver_longitude) {
        window.driverLocation = {
            latitude: Number(booking.driver_latitude),
            longitude: Number(booking.driver_longitude),
        }
        document.getElementById('trip-status').textContent = 'Driver is on the way'
        document.getElementById('trip-status-detail').textContent = 'Live location updated just now.'
        showDriverMap(Number(booking.driver_latitude), Number(booking.driver_longitude), true)
    }
}

async function handleCompleteTrip() {
    const booking = load('current_booking')
    const message = document.getElementById('trip-complete-message')
    const button = document.getElementById('complete-trip-button')
    if (!booking || !button) return
    if (!Number.isInteger(Number(booking.id)) || Number(booking.id) < 1) {
        message.textContent = 'This booking is out of date. Please reopen it from your bookings.'
        button.disabled = true
        return
    }
    button.disabled = true
    const res = await completeBooking(booking.id)
    if (res.ok) {
        save('current_booking', res.data.booking)
        clearInterval(window.tripRefreshTimer)
        document.getElementById('trip-status').textContent = 'Trip completed'
        document.getElementById('trip-status-detail').textContent = 'This booking is now in Previous bookings.'
        button.hidden = true
        message.textContent = 'Thanks for riding with Connect.'
        loadBookingSidebar()
    } else {
        button.disabled = false
        message.textContent = res.data.error || 'Could not complete this trip.'
    }
}

function showBookingConfirmation(booking) {
    document.getElementById('booking-form').style.display = 'none'
    const confirm = document.getElementById('booking-confirmation')
    confirm.style.display = 'block'
    document.getElementById('booking-number').textContent = booking.booking_number
    setTripStatus('Waiting for admin confirmation', 'Your booking has been sent to the operator.')
    window.bookingConfirmationTimer = setInterval(() => checkBookingConfirmation(booking.booking_number), 5000)
}

async function checkBookingConfirmation(bookingNumber) {
    const res = await getMyBookings()
    if (!res.ok) return
    const booking = res.data.find(item => item.booking_number === bookingNumber)
    if (!booking) return
    save('current_booking', booking)
    if (booking.status === 'confirmed') {
        clearInterval(window.bookingConfirmationTimer)
        window.location.href = 'trip.html'
    }
}

async function refreshBookingStatus(bookingNumber) {
    const res = await getMyBookings()
    if (!res.ok) return
    const updated = res.data.find(b => b.booking_number === bookingNumber)
    if (updated) {
        if (updated.driver_name) showDriver(updated)
        else setTripStatus('Waiting for driver assignment...', 'You will receive an SMS when a driver is assigned.')
    }
}

function setTripStatus(title, detail) {
    document.getElementById('trip-status').textContent = title
    document.getElementById('trip-status-detail').textContent = detail
}

function showDriver(booking) {
    setTripStatus('Driver assigned', 'Your driver is on the way. Live location will appear below.')
    const driverBox = document.getElementById('driver-box')
    driverBox.style.display = 'block'
    document.getElementById('driver-name').textContent = booking.driver_name
    document.getElementById('driver-phone').textContent = booking.driver_phone
    document.getElementById('bus-number').textContent = `Bus: ${booking.driver_bus}`
    if (booking.driver_latitude && booking.driver_longitude) {
        setTripStatus('Driver is on the way', 'Live location updated just now.')
        showDriverMap(Number(booking.driver_latitude), Number(booking.driver_longitude))
    }
}

function initializeTripMap() {
    if (!window.L) return
    const defaultLocation = [-1.286389, 36.817223]
    showDriverMap(defaultLocation[0], defaultLocation[1], false)
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(position => {
            showUserLocation(position.coords.latitude, position.coords.longitude)
        }, () => {})
    }
}

function showUserLocation(latitude, longitude) {
    if (!window.L || !window.driverMap) return
    if (!window.userMarker) {
        window.userMarker = L.circleMarker([latitude, longitude], {
            radius: 8,
            color: '#176b45',
            fillColor: '#2eaa64',
            fillOpacity: 1,
            weight: 3,
        }).addTo(window.driverMap)
        window.userMarker.bindPopup('Your location')
    } else {
        window.userMarker.setLatLng([latitude, longitude])
    }
    window.driverMap.setView([latitude, longitude], 14)
}

function showDriverMap(latitude, longitude, moveMarker = true) {
    const mapElement = document.getElementById('driver-map')
    if (!mapElement || !window.L) return
    if (!window.driverMap) {
        window.driverMap = L.map(mapElement).setView([latitude, longitude], 14)
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
        }).addTo(window.driverMap)
    }
    if (moveMarker) {
        if (!window.driverMarker) {
            window.driverMarker = L.marker([latitude, longitude]).addTo(window.driverMap)
            window.driverMarker.bindPopup('Current driver location')
            window.driverMap.setView([latitude, longitude])
        } else {
            window.driverMap.setView([latitude, longitude])
            window.driverMarker.setLatLng([latitude, longitude])
        }
        if (window.userMarker) {
            window.driverMap.fitBounds(L.featureGroup([window.driverMarker, window.userMarker]).getBounds(), { padding: [40, 40] })
        }
    }
}
// Operator-side logic
function load(key) {
    try { return JSON.parse(localStorage.getItem(key)) } catch { return null }
}

function save(key, value) { localStorage.setItem(key, JSON.stringify(value)) }

async function handleAdminSignup(e) {
    e.preventDefault()
    const data = Object.fromEntries(new FormData(document.getElementById('admin-signup-form')))
    const res = await apiCall('/users/admin-signup/', 'POST', data)
    const error = document.getElementById('error')
    if (res.ok) {
        save('admin', res.data.user)
        save('admin_company', data.company)
        window.location.href = 'dashboard.html'
    } else {
        const firstError = Object.values(res.data)[0]
        error.textContent = Array.isArray(firstError) ? firstError[0] : firstError || 'Could not create admin account.'
    }
}

// ADMIN LOGIN
async function handleAdminLogin(e) {
    e.preventDefault()
    const data = {
        phone_number: document.getElementById('phone').value,
        password: document.getElementById('password').value,
    }
    const res = await login(data)
    if (res.ok && res.data.user.is_admin) {
        save('admin', res.data.user)
        const company = document.getElementById('company').value
        if (company) save('admin_company', company)
        else localStorage.removeItem('admin_company')
        window.location.href = 'dashboard.html'
    } else {
        document.getElementById('error').textContent = res.data.error || 'Use an active admin account and the correct password.'
    }
}

// DASHBOARD
async function loadDashboard() {
    const companyId = load('admin_company')
    const res = await getCompanyBookings(companyId)
    if (!res.ok) { window.location.href = 'login.html'; return }

    const bookings = res.data
    const pending = bookings.filter(b => b.status === 'pending').length
    const confirmed = bookings.filter(b => b.status === 'confirmed').length
    const total = bookings.length

    document.getElementById('total').textContent = total
    document.getElementById('pending').textContent = pending
    document.getElementById('confirmed').textContent = confirmed

    const list = document.getElementById('booking-list')
    list.innerHTML = ''
    bookings.forEach(booking => {
        const row = document.createElement('div')
        row.className = 'booking-row'
        row.innerHTML = `
            <div>
                <div class="booking-num">${booking.booking_number}</div>
                <div class="booking-info">${booking.user_name} • ${booking.route_name}</div>
                <div class="booking-info">${booking.pickup_location}</div>
            </div>
            <span class="badge badge-${booking.status}">${booking.status}</span>
        `
        row.onclick = () => {
            save('selected_booking', booking)
            window.location.href = 'booking-detail.html'
        }
        list.appendChild(row)
    })
}

async function handleCreateDriver(e) {
    e.preventDefault()
    const form = document.getElementById('driver-form')
    const data = Object.fromEntries(new FormData(form))
    const message = document.getElementById('driver-message')
    if (!data.company) {
        message.textContent = 'Select a company by logging in again.'
        return
    }
    const res = await createDriver(data)
    if (res.ok) {
        message.textContent = `${res.data.name} added successfully.`
        form.reset()
    } else {
        message.textContent = res.data.error || 'Could not add driver.'
    }
}

// BOOKING DETAIL
function loadBookingDetail() {
    const booking = load('selected_booking')
    if (!booking) { window.location.href = 'dashboard.html'; return }

    document.getElementById('booking-number').textContent = booking.booking_number
    document.getElementById('passenger-name').textContent = booking.user_name
    document.getElementById('passenger-phone').textContent = booking.user_phone
    document.getElementById('route').textContent = booking.route_name
    document.getElementById('company').textContent = booking.company_name
    document.getElementById('pickup').textContent = booking.pickup_location
    document.getElementById('status').innerHTML = `<span class="badge badge-${booking.status}">${booking.status}</span>`

    if (booking.status === 'pending') {
        document.getElementById('assign-section').style.display = 'block'
        loadDrivers(booking.route)
    }

    if (booking.driver_name) {
        document.getElementById('driver-section').style.display = 'block'
        document.getElementById('driver-name').textContent = booking.driver_name
        document.getElementById('driver-phone').textContent = booking.driver_phone
        document.getElementById('driver-bus').textContent = booking.driver_bus
        if (booking.stage_departure_minutes !== null && booking.stage_departure_minutes !== undefined) {
            document.getElementById('departure-minutes').value = booking.stage_departure_minutes
        }
    }
}

async function handleSetStageDeparture() {
    const booking = load('selected_booking')
    const minutes = document.getElementById('departure-minutes').value
    const error = document.getElementById('departure-error')
    const message = document.getElementById('departure-message')
    error.textContent = ''
    message.textContent = ''
    const res = await setStageDeparture(booking.id, minutes)
    if (!res.ok) {
        error.textContent = res.data.error || 'Could not update ETA.'
        return
    }
    save('selected_booking', res.data)
    document.getElementById('departure-minutes').value = res.data.stage_departure_minutes
    message.textContent = 'Passenger ETA updated.'
}

async function loadDrivers() {
    const res = await getDrivers(load('admin_company'))
    if (res.ok) {
        const select = document.getElementById('driver-select')
        select.innerHTML = '<option value="">-- Select Driver --</option>'
        res.data.forEach(driver => {
            const option = document.createElement('option')
            option.value = driver.id
            option.textContent = `${driver.name} — Bus ${driver.bus_number}`
            select.appendChild(option)
        })
    }
}

async function handleAssignDriver(e) {
    e.preventDefault()
    const booking = load('selected_booking')
    const driverId = document.getElementById('driver-select').value

    if (!driverId) {
        document.getElementById('assign-error').textContent = 'Select a driver'
        return
    }

    const res = await assignDriver(booking.id, driverId)
    if (res.ok) {
        save('selected_booking', res.data.booking)
        alert('Driver assigned! SMS sent to passenger.')
        window.location.href = 'dashboard.html'
    } else {
        document.getElementById('assign-error').textContent = res.data.error
    }
}
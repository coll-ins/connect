// Django API client
const API_HOST = window.location.hostname || '127.0.0.1'
const BASE_URL = `http://${API_HOST}:8000/api`

function getCookie(name) {
    const value = document.cookie.split('; ').find(row => row.startsWith(`${name}=`))
    return value ? decodeURIComponent(value.split('=')[1]) : ''
}

async function ensureCsrfToken() {
    await fetch(`${BASE_URL}/users/csrf/`, { credentials: 'include' })
    return getCookie('csrftoken')
}

async function apiCall(endpoint, method = 'GET', data = null) {
    const csrfToken = method !== 'GET' ? await ensureCsrfToken() : ''
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
            ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        credentials: 'include',
    }
    if (data) options.body = JSON.stringify(data)

    try {
        const response = await fetch(`${BASE_URL}${endpoint}`, options)
        const json = await response.json()
        return { ok: response.ok, data: json, status: response.status }
    } catch (error) {
        return { ok: false, data: { error: 'Network error. Check connection.' } }
    }
}

// Auth
const signup = (data) => apiCall('/users/signup/', 'POST', data)
const login = (data) => apiCall('/users/login/', 'POST', data)
const logout = () => apiCall('/users/logout/', 'POST')

// Companies & Routes
const getCompanies = (location = '') => apiCall(`/companies/?location=${encodeURIComponent(location)}`)
const getRoutes = (companyId) => apiCall(`/companies/${companyId}/routes/`)

// Bookings
const createBooking = (data) => apiCall('/bookings/create/', 'POST', data)
const getMyBookings = () => apiCall('/bookings/mine/')
const getAllBookings = () => apiCall('/bookings/all/')
const getCompanyBookings = (companyId) => companyId
    ? apiCall(`/bookings/all/?company_id=${companyId}`)
    : apiCall('/bookings/all/')
const getBookingDetail = (id) => apiCall(`/bookings/${id}/`)
const assignDriver = (bookingId, driverId) =>
    apiCall(`/bookings/${bookingId}/assign-driver/`, 'POST', { driver_id: driverId })
const completeBooking = (bookingId) =>
    apiCall(`/bookings/${bookingId}/complete/`, 'POST')

// Drivers
const getDrivers = (companyId = '') => apiCall(`/drivers/?company_id=${companyId}`)
const createDriver = (data) => apiCall('/drivers/create/', 'POST', data)
const updateDriverLocation = (driverId, latitude, longitude) =>
    apiCall(`/drivers/${driverId}/location/`, 'POST', { latitude, longitude })
const updatePassengerLocation = (bookingId, latitude, longitude) =>
    apiCall(`/bookings/${bookingId}/passenger-location/`, 'POST', { latitude, longitude })
const getDriverBookings = (driverId) => apiCall(`/bookings/driver/${driverId}/active/`)
const setStageDeparture = (bookingId, minutes) =>
    apiCall(`/bookings/${bookingId}/stage-departure/`, 'POST', { minutes })
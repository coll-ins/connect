from django.urls import path
from . import views

urlpatterns = [
    path('', views.get_companies, name='get_companies'),
    path('create/', views.create_company, name='create_company'),
    path('<int:company_id>/', views.update_company, name='update_company'),

    path('routes/', views.get_routes, name='get_routes'),
    path('routes/health/', views.route_health, name='route_health'),
    path('routes/create/', views.create_route, name='create_route'),
    path('routes/<int:route_id>/', views.manage_route, name='manage_route'),
    path('routes/<int:route_id>/pickup-stages/', views.get_route_pickup_stages, name='get_route_pickup_stages'),
    path('routes/<int:route_id>/pickup-stages/create/', views.create_pickup_stage, name='create_pickup_stage'),
    path('routes/<int:route_id>/plan/', views.route_plan, name='route_plan'),
    path('pickup-stages/<int:stage_id>/', views.manage_pickup_stage, name='manage_pickup_stage'),
    path('pickup-stages/<int:stage_id>/approve/', views.approve_pickup_stage, name='approve_pickup_stage'),
    path('pickup-stages/<int:stage_id>/deactivate/', views.deactivate_pickup_stage, name='deactivate_pickup_stage'),
    path('<int:company_id>/routes/', views.get_routes, name='get_company_routes'),

    path('trips/', views.get_trips, name='get_trips'),
    path('trips/create/', views.create_trip, name='create_trip'),
    path('<int:company_id>/trips/', views.get_trips, name='get_company_trips'),

    path('trips/<int:trip_id>/', views.get_trip_details, name='get_trip_details'),
    path(
        'trips/<int:trip_id>/status/',
        views.update_trip_status,
        name='update_trip_status'
    ),
    path(
        'trips/<int:trip_id>/capacity/',
        views.update_trip_capacity,
        name='update_trip_capacity'
    ),
    path(
        'operator-routes/',
        views.operator_route_assignments,
        name='operator_route_assignments'
    ),
    path(
        'operator-routes/<int:user_id>/',
        views.set_operator_routes,
        name='set_operator_routes'
    ),
    path(
        '<int:company_id>/analytics/',
        views.company_analytics,
        name='company_analytics'
    ),
    path(
        'routes/<int:route_id>/map/',
        views.route_map_data,
        name='route-map-data'
    ),
]

from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .views import rent_vehicle

urlpatterns = [
    path('', views.home, name='home'),
    path('vehicles/', views.vehicles, name='vehicles'),
    path('helpdesk/', views.helpdesk, name='helpdesk'),
    path('offers/', views.offers, name='offers'),
    path('rent-history/', views.rent_history, name='rent_history'),
    path('list-vehicle/', views.list_vehicle, name='list_vehicle'),
    path('become-driver/', views.become_driver, name='become_driver'),

    # Login & Logout
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('signup/', views.signup_view, name='signup'),

    path("rent/<int:vehicle_id>/", rent_vehicle, name="rent_vehicle"),
    path('your-vehicles/', views.your_vehicles, name='your_vehicles'),

    path(
        'vehicles/<int:vehicle_id>/booked-dates/',
        views.vehicle_booked_dates,
        name='vehicle_booked_dates'
    ),

    # CAPTCHA
    path("captcha/", views.captcha_image, name="captcha"),


    path('payment/checkout/', views.create_checkout_session, name='create_checkout_session'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path("rent/success/", views.rent_success_callback, name="rent_success_callback"),

    path('payments/', views.payments_view, name='payments'),
    path('payment/create/', views.create_checkout_session, name='create_checkout_session'),
    path('payment/success_handler/', views.payment_success_handler, name='payment_success_handler'),

    path('fix-graph/', views.auto_fix_graph, name='fix_graph'),

    path('edit-vehicle/<int:vehicle_id>/', views.edit_vehicle, name='edit_vehicle'),
    
    path('toggle-status/<int:vehicle_id>/', views.toggle_vehicle_status, name='toggle_vehicle_status'),
    path('toggle-status/<int:vehicle_id>/', views.toggle_vehicle_status, name='toggle_vehicle_status'),
]

from django.contrib import admin
from .models import (
    Vehicle, 
    VehicleImage, 
    Rental, 
    Driver, 
    Wallet, 
    WalletTransaction,
    Review
)

admin.site.site_header = "GoWheels Admin Page"
admin.site.site_title = "GoWheels Admin Portal"
admin.site.index_title = "Welcome to GoWheels admin Dashboard"

# ==========================================
# VEHICLE ADMIN
# ==========================================

class VehicleImageInline(admin.TabularInline):
    model = VehicleImage
    extra = 1

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('vehicle_name', 'category', 'price_per_day', 'available', 'owner')
    list_filter = ('category', 'vehicle_type', 'available')
    search_fields = ('vehicle_name', 'pickup_location')
    list_editable = ('available',)
    ordering = ('vehicle_name',)
    inlines = [VehicleImageInline]


# ==========================================
# DRIVER ADMIN
# ==========================================

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('name', 'age', 'experience_years', 'rating', 'price_per_day', 'available')
    list_editable = ('available',)
    search_fields = ('name',)
    # Add fields to make it easy to upload photos directly from Admin
    fields = ('name', 'age', 'phone_number', 'experience_years', 'rating', 'price_per_day', 'photo', 'aadhaar_image', 'license_image', 'available')


# ==========================================
# RENTAL ADMIN
# ==========================================

@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'vehicle', 'start_date', 'end_date', 'total_price', 'payment_mode', 'rented_at')
    list_filter = ('payment_mode', 'drive_type', 'rented_at')
    search_fields = ('user__username', 'vehicle__vehicle_name', 'full_name')
    date_hierarchy = 'rented_at'
    ordering = ('-start_date',)


# ==========================================
# WALLET ADMIN
# ==========================================

class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    readonly_fields = ('transaction_type', 'amount', 'status', 'created_at')
    can_delete = False

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'updated_at')
    search_fields = ('user__username', 'user__email')
    inlines = [WalletTransactionInline] # Shows transaction history inside the Wallet page

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'transaction_type', 'amount', 'status', 'created_at')
    list_filter = ('transaction_type', 'status')
    search_fields = ('wallet__user__username', 'description')

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('vehicle', 'user', 'vehicle_avg', 'driver_rating', 'created_at')
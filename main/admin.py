from django.contrib import admin
from .models import (
    Vehicle, 
    VehicleImage, 
    Rental, 
    DriverApplication, 
    Driver, 
    Wallet, 
    WalletTransaction,
    Review
)

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
# DRIVER APPLICATION ADMIN (With Approval Action)
# ==========================================

@admin.register(DriverApplication)
class DriverApplicationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'status', 'applied_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'user__username')
    actions = ['approve_driver']

    @admin.action(description="Approve selected driver applications")
    def approve_driver(self, request, queryset):
        created = 0
        skipped = 0

        for app in queryset:
            # Skip if already approved
            if app.status == 'approved':
                skipped += 1
                continue

            # Create driver
            Driver.objects.create(
                application=app,  # <--- ADD THIS EXACT LINE HERE!
                name=app.full_name,
                age=app.age,
                phone_number=app.phone_number,
                experience_years=app.experience_years,
                rating=5.0,
                price_per_day=app.price_per_day,
                aadhaar_image=app.aadhaar_image,
                license_image=app.license_image,
                photo=app.profile_photo,
                available=True
            )

            # Update application status
            app.status = 'approved'
            app.save()
            created += 1

        self.message_user(
            request,
            f"{created} driver(s) created, {skipped} already approved."
        )

# ==========================================
# DRIVER ADMIN
# ==========================================

@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('name', 'age', 'experience_years', 'rating', 'price_per_day', 'available')
    list_editable = ('available',)
    search_fields = ('name',)


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
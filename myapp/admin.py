from django.contrib import admin
from .models import Business, SearchHistory, BusinessNiche


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ('name', 'postal_code', 'niche', 'phone', 'email', 'created_at')
    list_filter = ('postal_code', 'niche', 'created_at')
    search_fields = ('name', 'postal_code', 'phone', 'email')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ('postal_code', 'niche', 'user', 'results_count', 'created_at')
    list_filter = ('postal_code', 'niche', 'created_at')
    search_fields = ('postal_code', 'niche', 'user__username')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(BusinessNiche)
class BusinessNicheAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('name',)

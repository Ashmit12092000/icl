
// Searchable Dropdown Initialization
document.addEventListener('DOMContentLoaded', function() {
    // Wait for jQuery and Select2 to be loaded
    if (typeof $ !== 'undefined' && typeof $.fn.select2 !== 'undefined') {
        initializeSearchableDropdowns();
    } else {
        // Retry after a short delay if libraries aren't loaded yet
        setTimeout(function() {
            if (typeof $ !== 'undefined' && typeof $.fn.select2 !== 'undefined') {
                initializeSearchableDropdowns();
            }
        }, 500);
    }
});

function initializeSearchableDropdowns() {
    // Initialize Select2 on all select elements with class 'searchable-dropdown'
    $('.searchable-dropdown').select2({
        placeholder: function() {
            return $(this).data('placeholder') || 'Search and select...';
        },
        allowClear: true,
        width: '100%',
        dropdownParent: function() {
            // Check if the select is inside a modal
            const modal = $(this).closest('.modal, [role="dialog"]');
            return modal.length ? modal : $('body');
        },
        templateResult: function(option) {
            if (!option.id) {
                return option.text;
            }
            
            // Custom formatting for options (if data attributes exist)
            const $option = $(option.element);
            const code = $option.data('code');
            const description = $option.data('description');
            
            if (code || description) {
                const $result = $('<span></span>');
                
                if (code) {
                    $result.append($('<strong></strong>').text(code + ' - '));
                }
                
                $result.append($('<span></span>').text(option.text));
                
                if (description) {
                    $result.append($('<br><small class="text-gray-400"></small>').text(description));
                }
                
                return $result;
            }
            
            return option.text;
        },
        templateSelection: function(option) {
            if (!option.id) {
                return option.text;
            }
            
            const $option = $(option.element);
            const code = $option.data('code');
            
            if (code) {
                return code + ' - ' + option.text;
            }
            
            return option.text;
        }
    });

    // Handle dynamic updates for searchable dropdowns
    $('.searchable-dropdown').on('select2:select', function(e) {
        const selectedData = e.params.data;
        const selectElement = $(this);
        
        // Trigger any custom change handlers
        if (typeof window.handleSearchableDropdownChange === 'function') {
            window.handleSearchableDropdownChange(selectElement, selectedData);
        }
        
        // Fire the original change event for existing handlers
        selectElement.trigger('change.original');
    });

    // Initialize location-specific dropdowns
    initializeLocationDropdowns();
    
    // Initialize item-specific dropdowns
    initializeItemDropdowns();
}

function initializeLocationDropdowns() {
    $('.location-dropdown').select2({
        placeholder: 'Search locations...',
        allowClear: true,
        width: '100%',
        templateResult: function(option) {
            if (!option.id) {
                return option.text;
            }
            
            const $option = $(option.element);
            const office = $option.data('office');
            const room = $option.data('room');
            const code = $option.data('code');
            
            const $result = $('<div></div>');
            
            if (code) {
                $result.append($('<strong class="text-blue-300"></strong>').text(code));
                $result.append(' - ');
            }
            
            if (office) {
                $result.append($('<span></span>').text(office));
                if (room) {
                    $result.append(', ' + room);
                }
            } else {
                $result.append($('<span></span>').text(option.text));
            }
            
            return $result;
        }
    });
}

function initializeItemDropdowns() {
    $('.item-dropdown').select2({
        placeholder: 'Search items...',
        allowClear: true,
        width: '100%',
        templateResult: function(option) {
            if (!option.id) {
                return option.text;
            }
            
            const $option = $(option.element);
            const code = $option.data('code');
            const category = $option.data('category');
            const unit = $option.data('unit');
            
            const $result = $('<div></div>');
            
            if (code) {
                $result.append($('<strong class="text-green-300"></strong>').text(code));
                $result.append(' - ');
            }
            
            $result.append($('<span></span>').text(option.text));
            
            if (category || unit) {
                const $meta = $('<div class="text-xs text-gray-400 mt-1"></div>');
                if (category) {
                    $meta.append('Category: ' + category);
                }
                if (unit) {
                    if (category) $meta.append(' | ');
                    $meta.append('Unit: ' + unit);
                }
                $result.append($meta);
            }
            
            return $result;
        }
    });
}

// Helper function to refresh searchable dropdowns
function refreshSearchableDropdowns() {
    $('.searchable-dropdown, .location-dropdown, .item-dropdown').select2('destroy');
    initializeSearchableDropdowns();
}

// Helper function to add new option to searchable dropdown
function addOptionToSearchableDropdown(selectElement, value, text, data = {}) {
    const option = new Option(text, value, false, false);
    
    // Add data attributes
    Object.keys(data).forEach(key => {
        $(option).data(key, data[key]);
    });
    
    selectElement.append(option);
    selectElement.trigger('change');
}

// Export functions for global use
window.SearchableDropdown = {
    refresh: refreshSearchableDropdowns,
    addOption: addOptionToSearchableDropdown,
    initialize: initializeSearchableDropdowns
};
